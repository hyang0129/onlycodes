#!/usr/bin/env node

/**
 * test-integration.js — End-to-end integration tests for the MCP passthrough stack.
 *
 * Covers the full call chain:
 *   exec-server.js  (MCP stdio)  →  interceptor  →  bridge-server  →  sub-mcp-manager  →  @github/mcp
 *          ↑                                                                 ↓
 *    mcp_bridge.py (in execute_code subprocess) ← UDS ←──────────────────────┘
 *
 * Acceptance criteria covered (from EPIC_13_DECOMPOSITION.md Sub-Issue 9 / issue #21):
 *   1. Full call chain test passes (mcp_bridge.call round-trip)
 *   2. GITHUB_TOKEN isolation verified in subprocess env AND session.jsonl (grep → 0 matches)
 *   3. Content-scan deny test passes (\bgh\b blocked with actionable error)
 *   4. Dispatch deny test passes (delete_repo blocked)
 *   5. Sub-MCP crash recovery test passes
 *   6. Tests pass against exec-server.bundle.mjs
 *
 * Run:
 *   node --test test/test-integration.js                           (source)
 *   ONLYCODES_TEST_BUNDLE=1 node --test test/test-integration.js   (bundle)
 *
 * Setting ONLYCODES_TEST_BUNDLE=1 switches the E2E execute_code tests to spawn
 * the bundled exec-server.bundle.mjs instead of exec-server.js. In-process
 * tests of the bridge server and sub-mcp-manager always run against the JS
 * sources because they import those modules directly (node:test does not
 * support dynamically redirecting ESM imports at runtime).
 */

import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import net from "node:net";
import path from "node:path";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// ─── Paths ───────────────────────────────────────────────────────────────────

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(__dirname, "..");
const SOURCE_ENTRY = join(REPO_ROOT, "exec-server.js");
const BUNDLE_ENTRY = join(REPO_ROOT, "exec-server.bundle.mjs");

// Bundle-mode is opt-in via the ONLYCODES_TEST_BUNDLE=1 env var. Passing a
// flag after the test file doesn't work under `node --test` (extra args are
// treated as additional test files), so we route this through the env.
// Usage: ONLYCODES_TEST_BUNDLE=1 node --test test/test-integration.js
const USE_BUNDLE = process.env.ONLYCODES_TEST_BUNDLE === "1";
const EXEC_SERVER_ENTRY = USE_BUNDLE ? BUNDLE_ENTRY : SOURCE_ENTRY;

// Log the mode so the test output shows which variant ran.
console.log(`[test-integration] mode: ${USE_BUNDLE ? "BUNDLE" : "SOURCE"} (${EXEC_SERVER_ENTRY})`);

// Unique socket path per test run (PID + random suffix) to avoid collisions with
// other tests, parallel runs, or stale sockets from crashed previous runs.
const TEST_RUN_TAG = `integ-${process.pid}-${Math.floor(Math.random() * 1e9)}`;
const TEST_SOCK_PATH = `/tmp/onlycodes-test-${TEST_RUN_TAG}.sock`;

// Each E2E test uses its own log dir so we can read only the entries from that
// specific execute_code call when checking for credential leaks.
function makeTempLogDir() {
  return mkdtemp(join(tmpdir(), `onlycodes-test-logs-${TEST_RUN_TAG}-`));
}

// ─── MCP stdio helper ────────────────────────────────────────────────────────

/**
 * Send a single tool request through a fresh exec-server stdio subprocess and
 * collect the response. The child is spawned per call (matches the pattern in
 * test/test-server.js) — this is simpler than reusing one process and means
 * each test can set its own env / logs dir without cross-contamination.
 *
 * @param {object} toolRequest    { method: "tools/call", params: {...} } or
 *                                { method: "tools/list", params: {} }
 * @param {object} [options]
 * @param {number} [options.timeoutMs=30000]
 * @param {object} [options.env]  Extra env vars for the child exec-server
 * @param {string} [options.entry=EXEC_SERVER_ENTRY]  Entry point to spawn
 * @returns {Promise<object>}     The JSON-RPC response with id=2
 */
async function callExecServer(toolRequest, options = {}) {
  const {
    timeoutMs = 30000,
    env = {},
    entry = EXEC_SERVER_ENTRY,
  } = options;

  return new Promise((resolve, reject) => {
    const child = spawn("node", [entry], {
      cwd: REPO_ROOT,
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env, ...env },
    });

    let stdout = "";
    let stderr = "";
    let settled = false;

    child.stdout.on("data", (chunk) => { stdout += chunk.toString(); });
    child.stderr.on("data", (chunk) => { stderr += chunk.toString(); });

    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        try { child.kill("SIGKILL"); } catch {}
        reject(new Error(`exec-server call timed out after ${timeoutMs}ms. stderr: ${stderr.slice(-500)}`));
      }
    }, timeoutMs);

    const initRequest = {
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: {
        protocolVersion: "2024-11-05",
        capabilities: {},
        clientInfo: { name: "integration-test", version: "1.0.0" },
      },
    };

    const initNotification = {
      jsonrpc: "2.0",
      method: "notifications/initialized",
      params: {},
    };

    const fullToolRequest = { jsonrpc: "2.0", id: 2, ...toolRequest };

    // Interleaved MCP handshake pattern (matches test-server.js).
    child.stdin.write(JSON.stringify(initRequest) + "\n");
    setTimeout(() => {
      child.stdin.write(JSON.stringify(initNotification) + "\n");
      setTimeout(() => {
        child.stdin.write(JSON.stringify(fullToolRequest) + "\n");
      }, 100);
    }, 200);

    const interval = setInterval(() => {
      if (settled) return;
      const lines = stdout.split("\n").filter((l) => l.trim());
      for (const line of lines) {
        try {
          const msg = JSON.parse(line);
          if (msg.id === 2) {
            settled = true;
            clearInterval(interval);
            clearTimeout(timer);
            try { child.kill(); } catch {}
            resolve(msg);
            return;
          }
        } catch {
          // Partial line; keep waiting
        }
      }
    }, 80);

    child.on("close", () => {
      if (settled) return;
      settled = true;
      clearInterval(interval);
      clearTimeout(timer);
      const lines = stdout.split("\n").filter((l) => l.trim());
      for (const line of lines) {
        try {
          const msg = JSON.parse(line);
          if (msg.id === 2) { resolve(msg); return; }
        } catch {}
      }
      reject(new Error(`exec-server closed without an id=2 response. stderr: ${stderr.slice(-500)}`));
    });
  });
}

/**
 * Call execute_code on a fresh exec-server child.
 * Thin wrapper around callExecServer for the common tool/call shape.
 */
function callExecuteCode(code, language, options = {}) {
  const request = {
    method: "tools/call",
    params: {
      name: "execute_code",
      arguments: { code, language },
    },
  };
  if (typeof options.timeoutSeconds === "number") {
    request.params.arguments.timeout_seconds = options.timeoutSeconds;
  }
  return callExecServer(request, options);
}

/**
 * Parse the structured execute_code output (the first content block is JSON).
 */
function parseExecuteCodeOutput(response) {
  assert.ok(response.result, `response must have .result, got: ${JSON.stringify(response).slice(0, 300)}`);
  assert.ok(response.result.content && response.result.content[0],
    `response must have .result.content[0], got: ${JSON.stringify(response).slice(0, 300)}`);
  const text = response.result.content[0].text;
  try {
    return JSON.parse(text);
  } catch {
    // Some error paths return a plain-text error rather than JSON; surface it raw.
    return { raw: text };
  }
}

// ─── In-process tests of bridge-server + sub-mcp-manager ─────────────────────
// These tests exercise the bridge/manager directly (no exec-server subprocess).
// They import the JS source modules, so they do not use the bundle — but the
// bundle rolls up the same source, so behaviour is identical.

// Set the socket path BEFORE importing bridge-server.js so its start() call
// picks it up via getBridgeSocketPath().
process.env.ONLYCODES_BRIDGE_SOCK = TEST_SOCK_PATH;

const { start: startBridge, stop: stopBridge } = await import("../bridge-server.js");
const subMcpManager = (await import("../sub-mcp-manager.js")).default;

let bridgeServer;

before(async () => {
  bridgeServer = startBridge();
  await new Promise((resolve, reject) => {
    if (bridgeServer.listening) return resolve();
    bridgeServer.once("listening", resolve);
    bridgeServer.once("error", reject);
  });
});

after(async () => {
  // Tear down sub-MCP children first so their stdio closes before we stop the
  // bridge and release the socket path.
  try { await subMcpManager.closeAll(); } catch {}
  if (bridgeServer) {
    try { stopBridge(bridgeServer); } catch {}
  }
  // Force event-loop drain: bridge-server installs persistent SIGTERM/SIGINT
  // handlers on the main process and the net.Server may keep the loop alive
  // briefly after close(). Schedule a hard exit so `node --test` terminates
  // promptly after all subtests have completed. Use setImmediate so the
  // after() hook still resolves cleanly first.
  setImmediate(() => {
    // If any test failed, process.exitCode is already set by node:test; just exit.
    process.exit(process.exitCode ?? 0);
  });
});

/**
 * Send a single NDJSON request to the running test bridge server and resolve
 * with the parsed response line. Used by the in-process round-trip tests.
 */
function sendBridgeRequest(req, timeoutMs = 15000) {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection(TEST_SOCK_PATH, () => {
      socket.write(JSON.stringify(req) + "\n");
    });
    let buf = "";
    const timer = setTimeout(() => {
      socket.destroy();
      reject(new Error(`bridge request timed out after ${timeoutMs}ms`));
    }, timeoutMs);
    socket.on("data", (chunk) => {
      buf += chunk.toString("utf8");
      const nl = buf.indexOf("\n");
      if (nl !== -1) {
        clearTimeout(timer);
        const line = buf.slice(0, nl);
        socket.destroy();
        try { resolve(JSON.parse(line)); }
        catch (e) { reject(new Error(`bad JSON from bridge: ${line}`)); }
      }
    });
    socket.on("error", (e) => { clearTimeout(timer); reject(e); });
  });
}

// --- Test 1: Full call chain (get_schema round-trip) ------------------------

test("full call chain: get_schema reaches sub-MCP and returns a schema", async () => {
  // Round-trip: bridge-server → interceptor (allow) → sub-mcp-manager →
  // spawn @modelcontextprotocol/server-github → MCP listTools → return schema.
  // "create_issue" is a tool exposed by @github/mcp that doesn't require auth
  // to enumerate — listTools works without GITHUB_TOKEN.
  const resp = await sendBridgeRequest({
    method: "get_schema",
    server: "github",
    tool: "create_issue",
  }, 20000);

  assert.ok(resp && typeof resp === "object", "response must be an object");
  assert.notEqual(resp.error, true, `expected success, got error: ${JSON.stringify(resp).slice(0, 300)}`);
  // The get_schema path returns the inputSchema directly (sub-mcp-manager.js
  // extracts tool.inputSchema). Verify it looks like a JSON schema.
  assert.equal(resp.type, "object", "schema must have type: object");
  assert.ok(resp.properties && typeof resp.properties === "object",
    "schema must have a properties object");
});

// --- Test 2: Full call chain via bridge — allowed call to real sub-MCP ------

test("full call chain: allowed call goes through the full dispatch path", async () => {
  // "create_issue" is NOT in the dispatch deny-list, so it passes the
  // interceptor and reaches the sub-MCP. Without a real token, the sub-MCP
  // returns an auth error — but the important thing is the full chain runs
  // (socket → bridge → interceptor → manager → child → back). We verify we
  // get a response, not an unhandled exception.
  const resp = await sendBridgeRequest({
    method: "call",
    server: "github",
    tool: "create_issue",
    args: { owner: "nonexistent-org-xyz", repo: "nonexistent", title: "test" },
  }, 20000);

  assert.ok(resp && typeof resp === "object", "response must be a structured object");
  // Either:
  //   (a) a valid MCP tool result (if somehow auth succeeds), or
  //   (b) an MCP tool result with isError:true carrying the GitHub auth error, or
  //   (c) a structured { error: true, message } from the manager.
  // All three prove the full call chain ran end-to-end.
  const looksLikeMcpResult = "content" in resp || "isError" in resp;
  const looksLikeStructuredError = resp.error === true && typeof resp.message === "string";
  assert.ok(looksLikeMcpResult || looksLikeStructuredError,
    `expected MCP result or structured error; got: ${JSON.stringify(resp).slice(0, 300)}`);
});

// --- Test 3: Dispatch deny — delete_repo blocked at bridge -----------------

test("dispatch deny: delete_repo is blocked by interceptor before sub-MCP", async () => {
  const resp = await sendBridgeRequest({
    method: "call",
    server: "github",
    tool: "delete_repo",
    args: { owner: "foo", repo: "bar" },
  });

  assert.equal(resp.error, true, "dispatch deny must return error:true");
  assert.ok(typeof resp.message === "string" && resp.message.length > 0,
    "dispatch deny must return a non-empty message");
  // The deny message from passthrough-config.json mentions delete_repo explicitly.
  assert.ok(/delete_repo|block|denied|irreversible/i.test(resp.message),
    `deny message should describe the block; got: ${resp.message}`);
});

// --- Test 4: Sub-MCP crash recovery -----------------------------------------

test("crash recovery: killing the sub-MCP child restarts it on next call", async () => {
  // First call: triggers lazy spawn. If unreachable, bail out with a skip-ish
  // assertion rather than failing the test on environment noise.
  const first = await subMcpManager.getSchema("github", "create_issue");
  assert.notEqual(first.error, true,
    `precondition: first getSchema call must succeed; got: ${JSON.stringify(first).slice(0, 200)}`);

  // Capture the child PID via the manager's internal state. We intentionally
  // reach into the private _servers map because there is no public getter —
  // this test is the crash-recovery contract for that internal API.
  const state = subMcpManager._servers.github;
  assert.ok(state, "internal state entry must exist after first call");
  assert.equal(state.status, "connected", "must be connected after first call");
  const pid = state.transport && state.transport.pid;
  assert.ok(Number.isInteger(pid) && pid > 0, `transport must expose a PID; got: ${pid}`);

  // Kill the child and wait long enough for the onclose handler in
  // sub-mcp-manager.js to mark state as "crashed".
  try { process.kill(pid, "SIGKILL"); } catch (e) {
    assert.fail(`failed to kill sub-MCP child pid=${pid}: ${e.message}`);
  }

  // Wait for the transport close handler to fire and flip state to crashed.
  // Poll rather than sleep fixed — avoids flakiness on slow CI.
  const crashDeadline = Date.now() + 5000;
  while (Date.now() < crashDeadline && state.status !== "crashed") {
    await new Promise((r) => setTimeout(r, 50));
  }
  assert.equal(state.status, "crashed",
    "manager must mark state as 'crashed' after the child dies");
  assert.ok(state.crashCount >= 1, "crashCount must increment on crash");

  // Next call must succeed by respawning the child. The manager's exponential
  // backoff starts at 1s, so this call takes ~1s longer than a cold start.
  const second = await subMcpManager.getSchema("github", "create_issue");
  assert.notEqual(second.error, true,
    `recovery: subsequent call must succeed after crash; got: ${JSON.stringify(second).slice(0, 200)}`);
  assert.equal(state.status, "connected", "state must be connected again after recovery");

  // New child must have a different PID than the one we killed.
  const newPid = state.transport && state.transport.pid;
  assert.ok(Number.isInteger(newPid) && newPid > 0, "new transport must expose a PID");
  assert.notEqual(newPid, pid, "respawned child must have a different PID");
});

// ─── End-to-end exec-server tests ────────────────────────────────────────────
// These spawn exec-server.js (or the bundle) as a fresh stdio subprocess and
// drive it through real MCP messages — exercising the full chain from the
// outside.

// --- Test 5: Content-scan deny — `gh` blocked ------------------------------

test("content-scan deny: execute_code bash containing `gh` is blocked with actionable error", async () => {
  const response = await callExecuteCode("gh pr list", "bash");

  // The interceptor returns isError:true with a Blocked: message (see
  // exec-server.js CallToolRequestSchema handler).
  assert.equal(response.result.isError, true,
    "execute_code with `gh` must return isError:true");
  const text = response.result.content[0].text;
  assert.ok(/blocked/i.test(text), `error text should say 'Blocked'; got: ${text}`);
  // The deny message from passthrough-config.json includes "gh" and mentions
  // mcp_bridge as the sanctioned alternative (the "actionable" part).
  assert.ok(/gh/i.test(text) && /mcp_bridge/i.test(text),
    `actionable error should mention gh and the mcp_bridge alternative; got: ${text}`);
});

// --- Test 6: Content-scan deny must NOT match substrings like 'github' ------

test("content-scan deny: `github.com` in a URL is NOT blocked (word-boundary)", async () => {
  // Tests the \bgh\b regex — 'github' must not trigger the rule. We use
  // python instead of bash so the content scanner's check is purely textual
  // and not confused by shell quoting.
  const code = 'print("url=https://github.com/foo/bar")';
  const response = await callExecuteCode(code, "python");
  // Should not be blocked — execution proceeds. The subprocess may still fail
  // if unshare isn't available, but the isError will carry a different reason.
  const text = response.result.content[0].text;
  assert.ok(!/Blocked:/i.test(text) || /network isolation|unshare/i.test(text),
    `'github.com' must not trigger the gh deny-rule; got: ${text}`);
});

// --- Test 7: Dispatch deny end-to-end — delete_repo via mcp_bridge ----------

test("dispatch deny E2E: mcp_bridge.call('github', 'delete_repo', ...) raises McpBridgeError", async () => {
  // Agent-style code: inside execute_code, call mcp_bridge.call with a tool
  // that the dispatch deny-list blocks. The Python client must surface this
  // as McpBridgeError (not a raw socket error), and the error message must
  // mention the block (actionable).
  const code = `
import sys
import mcp_bridge
try:
    mcp_bridge.call("github", "delete_repo", {"owner": "x", "repo": "y"})
    print("NO_ERROR_RAISED")
except mcp_bridge.McpBridgeError as e:
    print("CAUGHT:" + str(e))
except Exception as e:
    print("OTHER_EXC:" + type(e).__name__ + ":" + str(e))
`;
  const response = await callExecuteCode(code, "python", { timeoutMs: 30000 });
  const out = parseExecuteCodeOutput(response);

  // The subprocess should have exited 0 (the try/except handles the error).
  assert.equal(out.exit_code, 0,
    `script should handle McpBridgeError gracefully; stderr: ${out.stderr}`);
  assert.ok(out.stdout.startsWith("CAUGHT:"),
    `expected McpBridgeError to be raised; got stdout: ${out.stdout}`);
  assert.ok(/delete_repo|block|denied|irreversible/i.test(out.stdout),
    `error message should describe the block; got: ${out.stdout}`);
});

// --- Test 8: GITHUB_TOKEN isolation in subprocess env ----------------------

test("credential isolation: GITHUB_TOKEN is absent from execute_code subprocess env", async () => {
  const fakeToken = `gh_INTEG_TEST_TOKEN_${TEST_RUN_TAG}`;
  const code = `
import os
val = os.environ.get("GITHUB_TOKEN", "NOT_SET")
print("GITHUB_TOKEN_IN_SUBPROCESS=" + val)
`;
  // Set GITHUB_TOKEN on the exec-server parent env; the stripping logic in
  // buildStrippedEnv() must remove it before the subprocess sees it.
  const response = await callExecuteCode(code, "python", {
    env: { GITHUB_TOKEN: fakeToken },
  });
  const out = parseExecuteCodeOutput(response);

  assert.equal(out.exit_code, 0, `script should exit 0; stderr: ${out.stderr}`);
  assert.ok(out.stdout.includes("GITHUB_TOKEN_IN_SUBPROCESS=NOT_SET"),
    `GITHUB_TOKEN must be stripped from subprocess env; got stdout: ${out.stdout}`);
  assert.ok(!out.stdout.includes(fakeToken),
    `fake token value must not appear in subprocess stdout; got: ${out.stdout}`);
});

// --- Test 9: GITHUB_TOKEN isolation in session.jsonl -----------------------

test("credential isolation: GITHUB_TOKEN is absent from session.jsonl (grep → 0 matches)", async () => {
  // Run exec-server with a dedicated logs dir and parent GITHUB_TOKEN set.
  // Then read the log file and grep for the token — must be 0 matches.
  //
  // NOTE: The default session log path is $REPO_ROOT/logs/session.jsonl (see
  // exec-server.js). We cannot easily redirect that to a temp dir without
  // modifying the server. Instead, we clear the log file before the test,
  // run a targeted execute_code, then read the log and assert the fake token
  // value does NOT appear anywhere.
  const logFile = join(REPO_ROOT, "logs", "session.jsonl");
  const fakeToken = `gh_SESSION_LOG_TEST_${TEST_RUN_TAG}`;

  // Clear the log file so we assert only about entries produced by this test.
  try { await rm(logFile, { force: true }); } catch {}

  // Run an execute_code call with GITHUB_TOKEN set on the parent env. Note:
  // the payload must not itself leak the token — we deliberately print "safe"
  // content so any token bytes in session.jsonl would have to come from env.
  const code = `
import os
# Only read the *presence* — never print the value (would defeat the test).
print("HAS_GITHUB_TOKEN=" + ("yes" if "GITHUB_TOKEN" in os.environ else "no"))
`;
  await callExecuteCode(code, "python", {
    env: { GITHUB_TOKEN: fakeToken },
  });

  // Read the log file; assert it exists and contains our call's entry.
  assert.ok(existsSync(logFile), "session.jsonl must be created by execute_code");
  const logContent = await readFile(logFile, "utf8");
  assert.ok(logContent.length > 0, "session.jsonl must have content after execute_code");

  // Grep-equivalent: count substring occurrences. MUST be 0.
  const matches = logContent.split(fakeToken).length - 1;
  assert.equal(matches, 0,
    `GITHUB_TOKEN value must not appear in session.jsonl; found ${matches} occurrences`);

  // Also assert the generic string "GITHUB_TOKEN" doesn't leak the *value*
  // through some other field. (The key name itself may appear in the code
  // that the subprocess printed — "GITHUB_TOKEN" as a string is allowed;
  // the *value* is what must never appear.)
  assert.ok(!logContent.includes(fakeToken),
    `session.jsonl must not contain the GITHUB_TOKEN value`);
});

// --- Test 10: Full call chain E2E — execute_code using mcp_bridge.get_schema ---

test("full call chain E2E: execute_code running mcp_bridge.get_schema returns a schema", async () => {
  // This exercises the FULL chain in one test: the stdio MCP server spawns
  // a subprocess, the subprocess imports mcp_bridge.py from its cwd, connects
  // over the UDS to the bridge-server running inside exec-server, which
  // forwards through the interceptor to the sub-MCP manager, which spawns
  // @github/mcp and calls listTools.
  const code = `
import json
import mcp_bridge
schema = mcp_bridge.get_schema("github", "create_issue")
# Print only the top-level type and property keys so we don't dump a giant
# schema into the test output.
print(json.dumps({"type": schema.get("type"), "has_properties": isinstance(schema.get("properties"), dict)}))
`;
  const response = await callExecuteCode(code, "python", { timeoutMs: 45000 });
  const out = parseExecuteCodeOutput(response);

  assert.equal(out.exit_code, 0,
    `script must exit 0; stdout: ${out.stdout}, stderr: ${out.stderr}`);
  const payload = JSON.parse(out.stdout);
  assert.equal(payload.type, "object",
    "schema fetched via full call chain must have type: object");
  assert.equal(payload.has_properties, true,
    "schema fetched via full call chain must have a properties object");
});
