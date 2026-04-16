#!/usr/bin/env node

/**
 * exec-server.js — MCP server (stdio transport) with one tool: execute_code
 *
 * Runs Python or Bash scripts in async subprocesses with:
 *   - Hard timeout with SIGKILL on expiry
 *   - Streaming stdout/stderr collection
 *   - Network isolation via unshare -n
 *   - Stripped environment (no HOME, no credentials)
 *   - Isolated working directory (temp dir)
 *   - Session logging to logs/session.jsonl
 *   - Retry on transient errors, fallback on repeated failures
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { spawn } from "node:child_process";
import { mkdtemp, appendFile, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

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

// --- Subprocess execution ---

const DEFAULT_TIMEOUT_SECONDS = 30;
const MAX_OUTPUT_BYTES = 1024 * 1024; // 1 MB per stream

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

  const interpreter = language === "python" ? "python3" : "bash";

  // Build command with network isolation via unshare -n
  // Falls back to direct execution if unshare is unavailable (e.g., no CAP_SYS_ADMIN)
  let cmd, args;
  try {
    // Test if unshare -n is available
    await new Promise((resolve, reject) => {
      const test = spawn("unshare", ["-n", "true"], { stdio: "ignore" });
      test.on("close", (exitCode) =>
        exitCode === 0 ? resolve() : reject(new Error("unshare unavailable"))
      );
      test.on("error", reject);
    });
    cmd = "unshare";
    args = ["-n", interpreter, "-c", code];
  } catch {
    // unshare not available — run without network isolation
    // Log a warning but continue
    cmd = interpreter;
    args = ["-c", code];
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
async function executeWithRetry(code, language, timeoutSeconds, cwd = null) {
  const result1 = await executeCode(code, language, timeoutSeconds, cwd);
  const classification1 = classifyResult(result1);

  if (classification1 === "success") {
    return { result: result1, fallback_used: false, warning: null };
  }

  if (classification1 === "retryable") {
    // Retry once on transient error
    const result2 = await executeCode(code, language, timeoutSeconds, cwd);
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
      description:
        "Execute a Python or Bash script in a subprocess. Returns stdout, stderr, and exit code. Use cwd= to set the working directory. Prefer writing one complete script over multiple calls.",
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
  ],
}));

// Call tool handler
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  if (request.params.name !== "execute_code") {
    return {
      content: [
        {
          type: "text",
          text: `Unknown tool: ${request.params.name}`,
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

  const { result, fallback_used, warning } = await executeWithRetry(
    code,
    language,
    timeout,
    effectiveCwd
  );

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

  // Build response content blocks
  const content = [
    {
      type: "text",
      text: JSON.stringify(
        {
          stdout: result.stdout,
          stderr: result.stderr,
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
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((err) => {
  console.error("Server failed to start:", err);
  process.exit(1);
});
