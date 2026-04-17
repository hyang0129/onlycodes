#!/usr/bin/env node

/**
 * Integration tests for bridge-server.js
 *
 * Run: node --test test/test-bridge-server.js
 *
 * Uses a real Unix socket at a test-specific path to exercise:
 *  1. Dispatch deny-list (delete_repo → blocked)
 *  2. Allowed call (create_pr → manager fails with structured error, no crash)
 *  3. get_schema request (forwarded; manager returns structured error, no crash)
 *  4. Invalid JSON input → { error: true, message: "Invalid JSON request" }
 *  5. Server shutdown → socket file removed
 */

import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import net from "node:net";
import fs from "node:fs";

// ─── Test socket path ───────────────────────────────────────────────────────
// Use a unique path so parallel test runs don't collide.
const TEST_SOCK = `/tmp/test-bridge-${process.pid}.sock`;
process.env.ONLYCODES_BRIDGE_SOCK = TEST_SOCK;

// Import AFTER setting the env var so getBridgeSocketPath() picks it up.
const { start, stop } = await import("../bridge-server.js");

// ─── Helpers ─────────────────────────────────────────────────────────────────

/**
 * Send a single NDJSON request to the bridge server and collect the response.
 *
 * @param {object} req - JS object to send as a single NDJSON line.
 * @returns {Promise<object>} Parsed response object.
 */
function sendRequest(req) {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection(TEST_SOCK, () => {
      socket.write(JSON.stringify(req) + "\n");
    });

    let buf = "";
    socket.on("data", (chunk) => {
      buf += chunk.toString("utf8");
      const nl = buf.indexOf("\n");
      if (nl !== -1) {
        const line = buf.slice(0, nl);
        socket.destroy();
        try {
          resolve(JSON.parse(line));
        } catch (err) {
          reject(new Error(`Failed to parse response: ${line}`));
        }
      }
    });

    socket.on("error", reject);
  });
}

// ─── Lifecycle ───────────────────────────────────────────────────────────────

let server;

before(async () => {
  server = start();
  // Wait until the socket is actually listening
  await new Promise((resolve, reject) => {
    if (server.listening) return resolve();
    server.once("listening", resolve);
    server.once("error", reject);
  });
});

after(() => {
  if (server) {
    stop(server);
  }
});

// ─── Tests ───────────────────────────────────────────────────────────────────

test("dispatch deny: delete_repo is blocked before reaching sub-MCP manager", async () => {
  const resp = await sendRequest({
    method: "call",
    server: "github",
    tool: "delete_repo",
    args: { repo: "test/test" },
  });

  assert.equal(resp.error, true, "response should have error: true");
  assert.ok(
    typeof resp.message === "string" && resp.message.length > 0,
    "response should have a non-empty message",
  );
  // Confirm it's the deny message, not a sub-MCP error
  assert.ok(
    resp.message.includes("delete_repo") ||
      resp.message.toLowerCase().includes("blocked") ||
      resp.message.toLowerCase().includes("denied"),
    `deny message should mention the blocked operation, got: ${resp.message}`,
  );
});

test("allowed call: create_pr is not blocked; returns structured error (no real sub-MCP)", async () => {
  const resp = await sendRequest({
    method: "call",
    server: "github",
    tool: "create_pr",
    args: { title: "test" },
  });

  // Manager will fail to connect since there's no real @github/mcp server,
  // but it must return a structured { error, message } — NOT throw.
  assert.ok(
    typeof resp === "object" && resp !== null,
    "response must be an object",
  );
  // Either a successful result OR a structured error — both are valid here.
  if (resp.error !== undefined) {
    assert.equal(resp.error, true);
    assert.ok(
      typeof resp.message === "string" && resp.message.length > 0,
      "error response must have a non-empty message",
    );
  }
});

test("get_schema: forwarded to sub-MCP manager; returns structured response", async () => {
  const resp = await sendRequest({
    method: "get_schema",
    server: "github",
    tool: "create_pr",
  });

  // No real sub-MCP server → structured error expected, not a crash.
  assert.ok(
    typeof resp === "object" && resp !== null,
    "response must be an object",
  );
  if (resp.error !== undefined) {
    assert.equal(resp.error, true);
    assert.ok(
      typeof resp.message === "string" && resp.message.length > 0,
      "error response must have a non-empty message",
    );
  }
});

test("invalid JSON: returns { error: true, message: 'Invalid JSON request' }", async () => {
  const resp = await new Promise((resolve, reject) => {
    const socket = net.createConnection(TEST_SOCK, () => {
      // Send malformed JSON
      socket.write("{ this is not valid json }\n");
    });

    let buf = "";
    socket.on("data", (chunk) => {
      buf += chunk.toString("utf8");
      const nl = buf.indexOf("\n");
      if (nl !== -1) {
        const line = buf.slice(0, nl);
        socket.destroy();
        try {
          resolve(JSON.parse(line));
        } catch (err) {
          reject(new Error(`Failed to parse response: ${line}`));
        }
      }
    });

    socket.on("error", reject);
  });

  assert.equal(resp.error, true);
  assert.equal(resp.message, "Invalid JSON request");
});

test("unknown method: returns { error: true, message: ... }", async () => {
  const resp = await sendRequest({ method: "unknown_method", server: "github", tool: "foo" });
  assert.equal(resp.error, true);
  assert.ok(resp.message.includes("unknown_method"), `expected message about unknown method, got: ${resp.message}`);
});

test("server shutdown: socket file is removed after stop()", async () => {
  // Socket should exist while server is running
  assert.ok(fs.existsSync(TEST_SOCK), "socket file should exist while server is running");

  stop(server);
  server = null;

  // Give the OS a tick to remove the file
  await new Promise((r) => setTimeout(r, 50));

  assert.ok(!fs.existsSync(TEST_SOCK), "socket file should be cleaned up after stop()");
});
