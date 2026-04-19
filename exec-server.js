#!/usr/bin/env node

/**
 * exec-server.js — MCP server (stdio transport) with tools: execute_code, list_tools
 *
 * Runs Python or Bash scripts in async subprocesses with:
 *   - Hard timeout with SIGKILL on expiry
 *   - Streaming stdout/stderr collection
 *   - Network isolation via unshare -n (hard required — not best-effort)
 *   - Stripped environment (no HOME, no credentials)
 *   - Isolated working directory (temp dir)
 *   - Session logging to logs/session.jsonl
 *   - Retry on transient errors, fallback on repeated failures
 *   - Bridge server for sub-MCP passthrough via mcp_bridge.py
 *   - Content scanning via interceptor.js
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { spawn } from "node:child_process";
import { mkdtemp, appendFile, mkdir } from "node:fs/promises";
import { copyFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import * as bridgeServer from "./bridge-server.js";
import { loadConfig, getBridgeSocketPath } from "./config-loader.js";
import { checkContent } from "./interceptor.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const LOG_DIR = join(__dirname, "logs");
const LOG_FILE = join(LOG_DIR, "session.jsonl");

// --- Environment stripping ---

const STRIPPED_VARS = [
  "HOME",
  "ANTHROPIC_API_KEY",
  "CLAUDE_API_KEY",
  "AWS_SECRET_ACCESS_KEY",
  "AWS_ACCESS_KEY_ID",
  "AWS_SESSION_TOKEN",
  "GITHUB_TOKEN",
  "GH_TOKEN",
  "OPENAI_API_KEY",
  "SSH_AUTH_SOCK",
  "SSH_AGENT_PID",
  "GPG_AGENT_INFO",
];

function buildStrippedEnv() {
  const env = { ...process.env };
  for (const key of STRIPPED_VARS) {
    delete env[key];
  }
  // Also strip anything containing KEY, SECRET, TOKEN, PASSWORD, CREDENTIAL
  for (const key of Object.keys(env)) {
    if (
      /KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL/i.test(key) &&
      key !== "TERM" &&
      key !== "COLORTERM"
    ) {
      delete env[key];
    }
  }
  return env;
}

// --- Session logger ---

async function logSession(entry) {
  try {
    await mkdir(LOG_DIR, { recursive: true });
    await appendFile(LOG_FILE, JSON.stringify(entry) + "\n");
  } catch {
    // Logging failure should not crash the server
  }
}

// --- Output canonicalisation -----------------------------------------------
//
// Sub-process output often contains non-deterministic noise — ANSI escape
// sequences, ephemeral temp paths, transient PIDs in tracebacks. Two calls
// that succeed identically can produce different stdout/stderr bytes. The
// prompt cache keys on byte-identical prefixes, so this noise blocks
// cache reuse. We strip the most common offenders before returning.

const _ANSI_RE = /\x1b\[[0-9;]*[A-Za-z]/g;
const _TMP_RE = /\/tmp\/[A-Za-z0-9_.-]*onlycodes-[A-Za-z0-9]+/g;

function canonicalizeOutput(text) {
  if (typeof text !== "string" || text.length === 0) return text;
  let out = text.replace(_ANSI_RE, "");
  out = out.replace(_TMP_RE, "<tmpdir>");
  // Normalise CRLF / lone CR — agent never needs to see them and they
  // create cache misses against runs that produced LF for the same content.
  out = out.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  return out;
}

// --- Helper module staging --------------------------------------------------
//
// Copy mcp_bridge.py (sub-MCP passthrough) and codebox.py (file-ops helpers
// with byte-stable output) into the agent's cwd so `import mcp_bridge` and
// `import codebox` work. Both are dropped per-cwd; copies are idempotent.

const _HELPER_MODULES = ["mcp_bridge.py", "codebox.py"];

function _stageHelperModules(workDir) {
  for (const fname of _HELPER_MODULES) {
    const src = join(__dirname, fname);
    const dst = join(workDir, fname);
    try {
      copyFileSync(src, dst);
    } catch (e) {
      console.error(`Warning: could not copy ${fname} to cwd: ${e.message}`);
    }
  }
}

// --- Subprocess execution ---

const DEFAULT_TIMEOUT_SECONDS = 30;
const MAX_OUTPUT_BYTES = 1024 * 1024; // 1 MB per stream

// --- Persistent Python kernel pool -----------------------------------------
//
// Python execute_code calls run inside a long-lived REPL keyed by cwd, so
// imports / variables / opened files survive across calls. The kernel is a
// child process running python_kernel.py and speaking length-prefixed JSON
// over stdin/stdout. Each request gets its own per-call timeout; a timeout
// kills the kernel and the next request lazily spawns a fresh one (state is
// lost, which we surface to the agent in stderr).
//
// Bash stays per-call stateless — shell-state-across-calls is more dangerous
// than helpful and matches typical CLI usage.

/** Map<cwd_string, KernelHandle> */
const _pythonKernels = new Map();

/** Set of cwd strings whose kernel was killed — next spawn surfaces a reset notice. */
const _kernelResetPending = new Set();

/**
 * @typedef {Object} KernelHandle
 * @property {import("node:child_process").ChildProcessWithoutNullStreams} child
 * @property {Buffer} stdoutBuf
 * @property {(value: any) => void | null} pendingResolve
 * @property {boolean} dead   Set when the process has exited or been killed.
 * @property {string} cwd
 */

function _killKernel(handle, reason) {
  if (handle.dead) return;
  handle.dead = true;
  try {
    handle.child.kill("SIGKILL");
  } catch {
    // Already dead.
  }
  if (handle.pendingResolve) {
    const resolve = handle.pendingResolve;
    handle.pendingResolve = null;
    resolve({
      stdout: "",
      stderr: `kernel reset: ${reason}`,
      exit_code: 1,
      duration_ms: 0,
      timed_out: reason === "timeout",
    });
  }
  _pythonKernels.delete(handle.cwd);
  _kernelResetPending.add(handle.cwd);
}

/** Spawn a fresh persistent Python kernel for a given cwd. */
async function _spawnPythonKernel(workDir) {
  const strippedEnv = buildStrippedEnv();
  strippedEnv["ONLYCODES_BRIDGE_SOCK"] = getBridgeSocketPath();

  // Ensure mcp_bridge.py and codebox.py are importable from inside the kernel.
  _stageHelperModules(workDir);

  const kernelScript = join(__dirname, "python_kernel.py");

  // Pick the same unshare strategy the per-call path uses, but only once at
  // kernel boot. The kernel itself runs inside the network-isolated namespace.
  const unshareAttempts = [
    {
      check: ["unshare", ["--user", "--map-root-user", "--net", "true"]],
      cmd: "unshare",
      args: ["--user", "--map-root-user", "--net", "python3", "-u", kernelScript],
    },
    {
      check: ["unshare", ["-n", "true"]],
      cmd: "unshare",
      args: ["-n", "python3", "-u", kernelScript],
    },
  ];
  let cmd, args;
  let unshareAvailable = false;
  for (const attempt of unshareAttempts) {
    try {
      await new Promise((resolve, reject) => {
        const test = spawn(attempt.check[0], attempt.check[1], { stdio: "ignore" });
        test.on("close", (exitCode) =>
          exitCode === 0 ? resolve() : reject(new Error("unshare unavailable"))
        );
        test.on("error", reject);
      });
      cmd = attempt.cmd;
      args = attempt.args;
      unshareAvailable = true;
      break;
    } catch {
      // try next
    }
  }
  if (!unshareAvailable) {
    throw new Error("network isolation (unshare -n) is required but not available on this system.");
  }

  const child = spawn(cmd, args, {
    cwd: workDir,
    env: strippedEnv,
    stdio: ["pipe", "pipe", "pipe"],
    detached: false,
  });

  /** @type {KernelHandle} */
  const handle = {
    child,
    stdoutBuf: Buffer.alloc(0),
    pendingResolve: null,
    dead: false,
    cwd: workDir,
  };

  // Length-prefixed framing parser. Each response is `<ascii_int>\n<N bytes JSON>`.
  let stderrAccum = "";
  child.stdout.on("data", (chunk) => {
    handle.stdoutBuf = Buffer.concat([handle.stdoutBuf, chunk]);
    while (handle.pendingResolve) {
      const newlineIdx = handle.stdoutBuf.indexOf(0x0a); // '\n'
      if (newlineIdx === -1) return;
      const headerStr = handle.stdoutBuf.slice(0, newlineIdx).toString("ascii").trim();
      const n = parseInt(headerStr, 10);
      if (!Number.isFinite(n) || n < 0) {
        // Garbled framing — treat as fatal kernel error.
        _killKernel(handle, "framing error");
        return;
      }
      if (handle.stdoutBuf.length < newlineIdx + 1 + n) return; // wait for more
      const payload = handle.stdoutBuf.slice(newlineIdx + 1, newlineIdx + 1 + n).toString("utf-8");
      handle.stdoutBuf = handle.stdoutBuf.slice(newlineIdx + 1 + n);
      let parsed;
      try {
        parsed = JSON.parse(payload);
      } catch (e) {
        _killKernel(handle, `bad JSON from kernel: ${e.message}`);
        return;
      }
      const resolve = handle.pendingResolve;
      handle.pendingResolve = null;
      resolve({
        stdout: typeof parsed.stdout === "string" ? parsed.stdout : "",
        stderr: typeof parsed.stderr === "string" ? parsed.stderr : "",
        exit_code: typeof parsed.exit_code === "number" ? parsed.exit_code : 0,
        duration_ms: 0, // filled in by caller
        timed_out: false,
      });
    }
  });

  child.stderr.on("data", (chunk) => {
    // Kernel-level stderr (interpreter crash, syntax error in kernel itself).
    // Cap at MAX_OUTPUT_BYTES to avoid runaway accumulation.
    if (stderrAccum.length < MAX_OUTPUT_BYTES) {
      stderrAccum += chunk.toString();
    }
  });

  child.on("close", (exitCode) => {
    handle.dead = true;
    if (handle.pendingResolve) {
      const resolve = handle.pendingResolve;
      handle.pendingResolve = null;
      resolve({
        stdout: "",
        stderr: `kernel died (exit ${exitCode}): ${stderrAccum.slice(-2000)}`,
        exit_code: 1,
        duration_ms: 0,
        timed_out: false,
      });
    }
    if (_pythonKernels.get(workDir) === handle) {
      _pythonKernels.delete(workDir);
    }
  });

  child.on("error", (err) => {
    handle.dead = true;
    if (handle.pendingResolve) {
      const resolve = handle.pendingResolve;
      handle.pendingResolve = null;
      resolve({
        stdout: "",
        stderr: `kernel spawn error: ${err.message}`,
        exit_code: 1,
        duration_ms: 0,
        timed_out: false,
      });
    }
    if (_pythonKernels.get(workDir) === handle) {
      _pythonKernels.delete(workDir);
    }
  });

  return handle;
}

async function _getOrSpawnKernel(workDir) {
  let handle = _pythonKernels.get(workDir);
  if (handle && !handle.dead) return handle;
  handle = await _spawnPythonKernel(workDir);
  _pythonKernels.set(workDir, handle);
  return handle;
}

/** Run code in the persistent kernel for `cwd`, with a per-call timeout. */
async function executePythonStateful(code, timeoutSeconds, cwd) {
  const startTime = Date.now();
  const handle = await _getOrSpawnKernel(cwd);

  // Check for a pending reset notice before we run. We defer the flag clear
  // until after the call resolves so that if the kernel dies again immediately
  // we do not lose the notice.
  const hadResetPending = _kernelResetPending.has(cwd);

  const result = await new Promise((resolve) => {
    if (handle.dead) {
      resolve({
        stdout: "",
        stderr: "kernel unavailable",
        exit_code: 1,
        duration_ms: Date.now() - startTime,
        timed_out: false,
      });
      return;
    }
    if (handle.pendingResolve) {
      // Should never happen — server serialises tool calls — but be safe.
      resolve({
        stdout: "",
        stderr: "kernel busy",
        exit_code: 1,
        duration_ms: Date.now() - startTime,
        timed_out: false,
      });
      return;
    }

    const timer = setTimeout(() => {
      _killKernel(handle, "timeout");
    }, timeoutSeconds * 1000);

    handle.pendingResolve = (result) => {
      clearTimeout(timer);
      result.duration_ms = Date.now() - startTime;
      resolve(result);
    };

    const payload = JSON.stringify({ code });
    const buf = Buffer.from(payload, "utf-8");
    try {
      handle.child.stdin.write(`${buf.length}\n`);
      handle.child.stdin.write(buf);
    } catch (e) {
      _killKernel(handle, `write error: ${e.message}`);
    }
  });

  if (hadResetPending) {
    _kernelResetPending.delete(cwd);
    result.stderr = '[kernel was reset before this call — prior state lost]\n' + result.stderr;
  }
  return result;
}

// Cleanly shut down all kernels on server exit.
process.on("exit", () => {
  for (const handle of _pythonKernels.values()) {
    try {
      handle.child.kill("SIGKILL");
    } catch {
      // ignore
    }
  }
});

/**
 * Execute code in an isolated subprocess.
 *
 * @param {string} code - The script to execute
 * @param {"python"|"bash"} language - Script language
 * @param {number} timeoutSeconds - Hard timeout
 * @param {string|null} cwd - Working directory for the subprocess. If null, a fresh temp dir is used.
 * @returns {Promise<{stdout: string, stderr: string, exit_code: number, duration_ms: number, timed_out: boolean}>}
 */
async function executeCode(code, language, timeoutSeconds, cwd = null) {
  const workDir = cwd ?? await mkdtemp(join(tmpdir(), "onlycodes-"));
  const strippedEnv = buildStrippedEnv();

  // Inject the bridge socket path into the subprocess env so mcp_bridge.py can connect
  strippedEnv['ONLYCODES_BRIDGE_SOCK'] = getBridgeSocketPath();

  // Stage mcp_bridge.py and codebox.py into cwd so user code can import them.
  _stageHelperModules(workDir);

  const interpreter = language === "python" ? "python3" : "bash";

  // Build command with network isolation via unshare -n
  // Hard requirement: if unshare is unavailable, return an error (no silent fallback)
  // Try methods in order of preference (prefer user-namespace variant which works without root):
  //   1. unshare --user --map-root-user --net  (works without CAP_SYS_ADMIN)
  //   2. unshare -n                             (requires CAP_SYS_ADMIN or privileged container)
  const unshareAttempts = [
    { check: ["unshare", ["--user", "--map-root-user", "--net", "true"]], cmdFn: () => ({ cmd: "unshare", args: ["--user", "--map-root-user", "--net", interpreter, "-c", code] }) },
    { check: ["unshare", ["-n", "true"]], cmdFn: () => ({ cmd: "unshare", args: ["-n", interpreter, "-c", code] }) },
  ];
  let cmd, args;
  let unshareAvailable = false;
  for (const attempt of unshareAttempts) {
    try {
      await new Promise((resolve, reject) => {
        const test = spawn(attempt.check[0], attempt.check[1], { stdio: "ignore" });
        test.on("close", (exitCode) =>
          exitCode === 0 ? resolve() : reject(new Error("unshare unavailable"))
        );
        test.on("error", reject);
      });
      const resolved = attempt.cmdFn();
      cmd = resolved.cmd;
      args = resolved.args;
      unshareAvailable = true;
      break;
    } catch {
      // Try next option
    }
  }
  if (!unshareAvailable) {
    // unshare not available — hard error, do not proceed without network isolation
    throw new Error("network isolation (unshare -n) is required but not available on this system.");
  }

  const startTime = Date.now();

  return new Promise((resolve) => {
    const child = spawn(cmd, args, {
      cwd: workDir,
      env: strippedEnv,
      stdio: ["ignore", "pipe", "pipe"],
      // Prevent the child from inheriting signal handlers
      detached: false,
    });

    let stdout = "";
    let stderr = "";
    let stdoutBytes = 0;
    let stderrBytes = 0;
    let timedOut = false;

    child.stdout.on("data", (chunk) => {
      if (stdoutBytes < MAX_OUTPUT_BYTES) {
        const text = chunk.toString();
        stdout += text;
        stdoutBytes += chunk.length;
      }
    });

    child.stderr.on("data", (chunk) => {
      if (stderrBytes < MAX_OUTPUT_BYTES) {
        const text = chunk.toString();
        stderr += text;
        stderrBytes += chunk.length;
      }
    });

    const timer = setTimeout(() => {
      timedOut = true;
      try {
        child.kill("SIGKILL");
      } catch {
        // Process may have already exited
      }
    }, timeoutSeconds * 1000);

    child.on("close", (exitCode) => {
      clearTimeout(timer);
      const duration_ms = Date.now() - startTime;

      if (timedOut) {
        resolve({
          stdout: stdout.trim(),
          stderr: "timeout",
          exit_code: -1,
          duration_ms,
          timed_out: true,
        });
      } else {
        resolve({
          stdout: stdout.trim(),
          stderr: stderr.trim(),
          exit_code: exitCode ?? 1,
          duration_ms,
          timed_out: false,
        });
      }
    });

    child.on("error", (err) => {
      clearTimeout(timer);
      const duration_ms = Date.now() - startTime;
      resolve({
        stdout: "",
        stderr: err.message,
        exit_code: 1,
        duration_ms,
        timed_out: false,
      });
    });
  });
}

// --- Retry / fallback logic ---

/**
 * Classify an execution result for retry/fallback decisions.
 *
 * @param {{exit_code: number, stderr: string, timed_out: boolean}} result
 * @returns {"success"|"retryable"|"non_retryable"}
 */
function classifyResult(result) {
  if (result.exit_code === 0) return "success";
  if (result.timed_out) return "retryable";
  // OOM killer typically sends SIGKILL (exit code 137)
  if (result.exit_code === 137) return "retryable";
  // Syntax errors, missing binaries — non-retryable
  return "non_retryable";
}

// Session-level fallback counter
let fallbackCount = 0;

/**
 * Execute with retry and fallback logic.
 *
 * 1. Retryable error (timeout, OOM) → retry same script once
 * 2. Non-retryable (syntax error, missing binary) → return error + stderr
 * 3. Second failure → fall back to built-in Bash, log fallback
 * 4. Two fallbacks in one session → surface warning
 *
 * @returns {{result: object, fallback_used: boolean, warning: string|null}}
 */
// Set ONLYCODES_PERSISTENT_KERNEL=1 in the server's env to route Python
// through the kernel pool. Default off — the stateless contract is what
// the agent's training prior expects, and the stateless arm is the
// canonical onlycode mode. The stateful variant is opted into by a
// separate MCP config.
const PERSISTENT_KERNEL_ENABLED =
  process.env.ONLYCODES_PERSISTENT_KERNEL === "1";

async function executeWithRetry(code, language, timeoutSeconds, cwd = null) {
  // Python optionally routes through the persistent kernel pool when
  // PERSISTENT_KERNEL_ENABLED is set; otherwise every call gets a fresh
  // subprocess (matching pre-kernel behavior). Bash always stateless.
  const runOnce = async () => {
    if (language === "python" && PERSISTENT_KERNEL_ENABLED) {
      const effectiveCwd =
        cwd ?? (await mkdtemp(join(tmpdir(), "onlycodes-")));
      return executePythonStateful(code, timeoutSeconds, effectiveCwd);
    }
    return executeCode(code, language, timeoutSeconds, cwd);
  };
  const result1 = await runOnce();
  const classification1 = classifyResult(result1);

  if (classification1 === "success") {
    return { result: result1, fallback_used: false, warning: null };
  }

  if (classification1 === "retryable") {
    // Retry once on transient error
    const result2 = await runOnce();
    const classification2 = classifyResult(result2);

    if (classification2 === "success") {
      return { result: result2, fallback_used: false, warning: null };
    }

    // Second failure — fall back
    fallbackCount++;
    const warning =
      fallbackCount >= 2
        ? "WARNING: Two fallbacks in this session. execute_code may be unreliable for this workload."
        : null;

    return {
      result: result2,
      fallback_used: true,
      warning,
    };
  }

  // Non-retryable — return error directly, let Claude revise
  return { result: result1, fallback_used: false, warning: null };
}

// --- MCP Server setup ---

const server = new Server(
  {
    name: "codebox",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// List tools handler
server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "execute_code",
      description: PERSISTENT_KERNEL_ENABLED
        ? "Execute a Python or Bash script. Returns stdout, stderr, and exit code. Use cwd= to set the working directory.\n\nPython runs in a PERSISTENT REPL keyed by cwd: variables, imports, opened files, and module-level state carry across calls (one kernel per cwd, lives for the session). Read a file once into a variable and reference it on later turns instead of re-reading it. The kernel resets only on per-call timeout or kernel crash — when that happens, stderr will say \"kernel reset\" and you must restage any state you need.\n\nBash runs in a FRESH subprocess each call — no state carries over. Use Python for stateful work and Bash only for one-shot shell commands.\n\nA `codebox` helper module is auto-imported into your cwd: `import codebox; codebox.read(path)`, `codebox.read_lines(path, start, end)`, `codebox.grep(pattern, path)`, `codebox.files(root)`, `codebox.edit_replace(path, old, new)`. Prefer it over hand-rolled subprocess.run(['cat', ...]) calls — its output is byte-stable across identical reads, which keeps prompt-cache reuse high."
        : "Execute a Python or Bash script in a subprocess. Returns stdout, stderr, and exit code. Use cwd= to set the working directory.\n\nIMPORTANT: Each call runs in a FRESH interpreter — no state, variables, or imports carry over between calls. Every script must be fully self-contained: include all imports, redefine any variables, and reopen any files it needs. Do NOT rely on results from a previous call being available. Prefer one longer self-contained script over multiple short dependent calls.\n\nA `codebox` helper module is auto-imported into your cwd: `import codebox; codebox.read(path)`, `codebox.read_lines(path, start, end)`, `codebox.grep(pattern, path)`, `codebox.files(root)`, `codebox.edit_replace(path, old, new)`. Prefer it over hand-rolled subprocess.run(['cat', ...]) calls — its output is byte-stable across identical reads, which keeps prompt-cache reuse high.",
      inputSchema: {
        type: "object",
        properties: {
          code: {
            type: "string",
            description: "The script source code to execute.",
          },
          language: {
            type: "string",
            enum: ["python", "bash"],
            description: "Script language: python or bash.",
          },
          timeout_seconds: {
            type: "number",
            description:
              "Hard timeout in seconds. Process is killed on expiry. Default: 30.",
          },
          cwd: {
            type: "string",
            description:
              "Working directory for the subprocess. If omitted, a fresh isolated temp directory is used.",
          },
        },
        required: ["code", "language"],
      },
    },
    {
      name: "list_tools",
      description: "Returns a manifest of available sub-MCP tools accessible via mcp_bridge from inside execute_code.",
      inputSchema: {
        type: "object",
        properties: {},
        required: []
      }
    },
  ],
}));

// Call tool handler
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name } = request.params;

  // Handle list_tools
  if (name === "list_tools") {
    const config = loadConfig();
    const lines = ['Available sub-MCP tools (call via mcp_bridge from inside execute_code):\n'];
    for (const srv of config.subMcpServers) {
      lines.push(`## ${srv.name}`);
      lines.push(`import mcp_bridge`);
      lines.push(`result = mcp_bridge.call("${srv.name}", "<tool_name>", {...})`);
      lines.push(`schema = mcp_bridge.get_schema("${srv.name}", "<tool_name>")\n`);
    }
    return { content: [{ type: "text", text: lines.join('\n') }] };
  }

  if (name !== "execute_code") {
    return {
      content: [
        {
          type: "text",
          text: `Unknown tool: ${name}`,
        },
      ],
      isError: true,
    };
  }

  const { code, language, timeout_seconds, cwd } = request.params.arguments;

  // Validate inputs
  if (!code || typeof code !== "string") {
    return {
      content: [{ type: "text", text: "Error: code is required and must be a string." }],
      isError: true,
    };
  }

  if (!["python", "bash"].includes(language)) {
    return {
      content: [
        {
          type: "text",
          text: 'Error: language must be "python" or "bash".',
        },
      ],
      isError: true,
    };
  }

  const timeout = typeof timeout_seconds === "number" && timeout_seconds > 0
    ? timeout_seconds
    : DEFAULT_TIMEOUT_SECONDS;

  const effectiveCwd = typeof cwd === "string" && cwd.length > 0 ? cwd : null;

  // Content scan: check code against deny-list before spawning subprocess
  const denied = checkContent(code);
  if (denied) {
    return { content: [{ type: "text", text: `Blocked: ${denied.message}` }], isError: true };
  }

  // Handle unshare unavailability as a hard error
  let result, fallback_used, warning;
  try {
    ({ result, fallback_used, warning } = await executeWithRetry(
      code,
      language,
      timeout,
      effectiveCwd
    ));
  } catch (err) {
    if (err.message && err.message.includes("network isolation")) {
      return {
        content: [{ type: "text", text: `Error: ${err.message}` }],
        isError: true,
      };
    }
    throw err;
  }

  // Log to session.jsonl
  await logSession({
    timestamp: new Date().toISOString(),
    language,
    cwd: effectiveCwd,
    code,
    stdout: result.stdout,
    stderr: result.stderr,
    exit_code: result.exit_code,
    duration_ms: result.duration_ms,
    fallback_used,
  });

  // Canonicalise stdout/stderr so byte-identical reads produce byte-identical
  // tool results, maximising prompt-cache reuse on subsequent turns.
  const canonStdout = canonicalizeOutput(result.stdout);
  const canonStderr = canonicalizeOutput(result.stderr);

  // Build response content blocks
  const content = [
    {
      type: "text",
      text: JSON.stringify(
        {
          stdout: canonStdout,
          stderr: canonStderr,
          exit_code: result.exit_code,
        },
        null,
        2
      ),
    },
  ];

  if (fallback_used) {
    content.push({
      type: "text",
      text: "[FALLBACK] execute_code failed twice. Consider using built-in Bash for this invocation.",
    });
  }

  if (warning) {
    content.push({
      type: "text",
      text: warning,
    });
  }

  return {
    content,
    isError: result.exit_code !== 0,
  };
});

// --- Start server ---

async function main() {
  // Start the bridge server so execute_code subprocesses can reach sub-MCP tools
  const bridge = bridgeServer.start();
  console.error(`Bridge server listening on ${getBridgeSocketPath()}`);

  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((err) => {
  console.error("Server failed to start:", err);
  process.exit(1);
});
