#!/usr/bin/env node

/**
 * Integration tests for exec-server.js
 *
 * Tests the core execute_code functionality:
 *   - Python and Bash execution
 *   - Hard timeout with SIGKILL
 *   - Structured output format
 *   - Session logging to JSONL
 *   - Stripped environment variables
 *   - Network isolation (if unshare available)
 *   - Retry/fallback logic
 *
 * Run: node test/test-server.js
 */

import { spawn } from "node:child_process";
import { readFile, rm, mkdir } from "node:fs/promises";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");
const LOG_FILE = join(ROOT, "logs", "session.jsonl");

let passed = 0;
let failed = 0;
const failures = [];

function assert(condition, message) {
  if (condition) {
    passed++;
    console.log(`  PASS: ${message}`);
  } else {
    failed++;
    failures.push(message);
    console.log(`  FAIL: ${message}`);
  }
}

/**
 * Send a JSON-RPC request to the MCP server via stdio and collect the response.
 */
async function callServer(request, timeoutMs = 15000) {
  return new Promise((resolve, reject) => {
    const child = spawn("node", [join(ROOT, "exec-server.js")], {
      cwd: ROOT,
      stdio: ["pipe", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });

    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      reject(new Error(`Server call timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    // MCP stdio protocol: send JSON-RPC messages separated by newlines
    // First, send initialize
    const initRequest = {
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: {
        protocolVersion: "2024-11-05",
        capabilities: {},
        clientInfo: { name: "test-client", version: "1.0.0" },
      },
    };

    const initNotification = {
      jsonrpc: "2.0",
      method: "notifications/initialized",
      params: {},
    };

    // Then send the actual request
    const toolRequest = {
      jsonrpc: "2.0",
      id: 2,
      ...request,
    };

    child.stdin.write(JSON.stringify(initRequest) + "\n");

    // Wait a bit for init to process, then send initialized notification and tool call
    setTimeout(() => {
      child.stdin.write(JSON.stringify(initNotification) + "\n");
      setTimeout(() => {
        child.stdin.write(JSON.stringify(toolRequest) + "\n");
      }, 100);
    }, 200);

    // Collect responses — look for the tool response (id: 2)
    let checkInterval = setInterval(() => {
      const lines = stdout.split("\n").filter((l) => l.trim());
      for (const line of lines) {
        try {
          const msg = JSON.parse(line);
          if (msg.id === 2) {
            clearInterval(checkInterval);
            clearTimeout(timer);
            child.kill();
            resolve(msg);
            return;
          }
        } catch {
          // Not valid JSON yet, keep waiting
        }
      }
    }, 100);

    child.on("close", () => {
      clearInterval(checkInterval);
      clearTimeout(timer);
      // Try to parse the last response
      const lines = stdout.split("\n").filter((l) => l.trim());
      for (const line of lines) {
        try {
          const msg = JSON.parse(line);
          if (msg.id === 2) {
            resolve(msg);
            return;
          }
        } catch {
          // Not valid JSON
        }
      }
      reject(new Error(`No response found. stdout: ${stdout}, stderr: ${stderr}`));
    });
  });
}

/**
 * Helper to call execute_code tool
 */
async function callExecuteCode(code, language, timeout_seconds, callTimeoutMs) {
  const request = {
    method: "tools/call",
    params: {
      name: "execute_code",
      arguments: { code, language },
    },
  };
  if (timeout_seconds !== undefined) {
    request.params.arguments.timeout_seconds = timeout_seconds;
  }
  return callServer(request, callTimeoutMs);
}

/**
 * Parse the structured output from execute_code response
 */
function parseOutput(response) {
  if (!response.result || !response.result.content || !response.result.content[0]) {
    throw new Error(`Unexpected response shape: ${JSON.stringify(response)}`);
  }
  return JSON.parse(response.result.content[0].text);
}

// --- Tests ---

async function testBashExecution() {
  console.log("\n--- Test: Bash execution ---");
  const response = await callExecuteCode('echo "hello world"', "bash");
  const output = parseOutput(response);

  assert(output.exit_code === 0, "Bash exits with code 0");
  assert(output.stdout === "hello world", "Bash stdout captured correctly");
  assert(output.stderr === "", "Bash stderr is empty on success");
}

async function testPythonExecution() {
  console.log("\n--- Test: Python execution ---");
  const response = await callExecuteCode('print("hello from python")', "python");
  const output = parseOutput(response);

  assert(output.exit_code === 0, "Python exits with code 0");
  assert(output.stdout === "hello from python", "Python stdout captured correctly");
}

async function testPythonMultiline() {
  console.log("\n--- Test: Python multiline script ---");
  const code = `
import json
data = {"a": 1, "b": [2, 3]}
print(json.dumps(data))
`;
  const response = await callExecuteCode(code, "python");
  const output = parseOutput(response);

  assert(output.exit_code === 0, "Multiline Python exits with code 0");
  const parsed = JSON.parse(output.stdout);
  assert(parsed.a === 1, "Python JSON output parsed correctly");
}

async function testHardTimeout() {
  console.log("\n--- Test: Hard timeout kills long-running process ---");
  // Use a 2-second timeout with a script that sleeps for 30 seconds
  const response = await callExecuteCode("sleep 30", "bash", 2, 30000);
  const output = parseOutput(response);

  assert(output.exit_code === -1, "Timed-out process returns exit_code -1");
  assert(output.stderr === "timeout", 'Timed-out process returns stderr "timeout"');
}

async function testStructuredOutput() {
  console.log("\n--- Test: Structured output format ---");
  const response = await callExecuteCode(
    'echo "out"; echo "err" >&2',
    "bash"
  );
  const output = parseOutput(response);

  assert("stdout" in output, "Output has stdout field");
  assert("stderr" in output, "Output has stderr field");
  assert("exit_code" in output, "Output has exit_code field");
  assert(output.stdout === "out", "stdout captured");
  assert(output.stderr === "err", "stderr captured");
}

async function testNonZeroExitCode() {
  console.log("\n--- Test: Non-zero exit code ---");
  const response = await callExecuteCode("exit 42", "bash");
  const output = parseOutput(response);

  assert(output.exit_code === 42, "Non-zero exit code preserved");
  assert(response.result.isError === true, "isError is true for non-zero exit");
}

async function testStrippedEnvHome() {
  console.log("\n--- Test: Stripped env — HOME not visible ---");
  const response = await callExecuteCode(
    'echo "HOME=$HOME"',
    "bash"
  );
  const output = parseOutput(response);

  assert(
    output.stdout === "HOME=" || !output.stdout.includes("/home/"),
    "HOME is stripped from subprocess environment"
  );
}

async function testStrippedEnvApiKey() {
  console.log("\n--- Test: Stripped env — ANTHROPIC_API_KEY not visible ---");
  // Set the env var in the parent process temporarily
  const oldKey = process.env.ANTHROPIC_API_KEY;
  process.env.ANTHROPIC_API_KEY = "sk-test-secret-key";

  const response = await callExecuteCode(
    'python3 -c "import os; print(os.environ.get(\'ANTHROPIC_API_KEY\', \'NOT_SET\'))"',
    "bash"
  );
  const output = parseOutput(response);

  // Restore
  if (oldKey) {
    process.env.ANTHROPIC_API_KEY = oldKey;
  } else {
    delete process.env.ANTHROPIC_API_KEY;
  }

  assert(
    output.stdout === "NOT_SET",
    "ANTHROPIC_API_KEY is stripped from subprocess environment"
  );
}

async function testSessionLogger() {
  console.log("\n--- Test: Session logger writes correct JSONL ---");

  // Read the log file — it should have entries from previous tests
  try {
    const logContent = await readFile(LOG_FILE, "utf8");
    const lines = logContent.trim().split("\n").filter((l) => l.trim());
    assert(lines.length > 0, "Session log has entries");

    const lastEntry = JSON.parse(lines[lines.length - 1]);
    assert("timestamp" in lastEntry, "Log entry has timestamp");
    assert("language" in lastEntry, "Log entry has language");
    assert("code" in lastEntry, "Log entry has code");
    assert("stdout" in lastEntry, "Log entry has stdout");
    assert("stderr" in lastEntry, "Log entry has stderr");
    assert("exit_code" in lastEntry, "Log entry has exit_code");
    assert("duration_ms" in lastEntry, "Log entry has duration_ms");
    assert(typeof lastEntry.duration_ms === "number", "duration_ms is a number");
    assert(typeof lastEntry.timestamp === "string", "timestamp is a string");
  } catch (err) {
    assert(false, `Session log readable: ${err.message}`);
  }
}

async function testNetworkIsolation() {
  console.log("\n--- Test: Network isolation ---");

  // Try to check if unshare is available first
  let unshareAvailable = false;
  try {
    await new Promise((resolve, reject) => {
      const test = spawn("unshare", ["-n", "true"], { stdio: "ignore" });
      test.on("close", (code) =>
        code === 0 ? resolve() : reject()
      );
      test.on("error", reject);
    });
    unshareAvailable = true;
  } catch {
    console.log("  SKIP: unshare -n not available (need CAP_SYS_ADMIN)");
  }

  if (unshareAvailable) {
    const response = await callExecuteCode(
      'curl -s --max-time 2 http://example.com 2>&1; echo "EXIT:$?"',
      "bash",
      10
    );
    const output = parseOutput(response);

    // With network isolation, curl should fail
    assert(
      output.stdout.includes("EXIT:") && !output.stdout.includes("EXIT:0"),
      "Network-isolated script cannot reach external endpoints"
    );
  }
}

async function testIsolatedWorkingDirectory() {
  console.log("\n--- Test: Isolated working directory ---");
  const response = await callExecuteCode("pwd", "bash");
  const output = parseOutput(response);

  assert(
    output.stdout.includes("onlycodes-") || output.stdout.includes("/tmp/"),
    "Working directory is an isolated temp dir, not user home"
  );
  assert(
    !output.stdout.includes("/home/"),
    "Working directory is not in user home"
  );
}

async function testSyntaxError() {
  console.log("\n--- Test: Syntax error returns stderr ---");
  const response = await callExecuteCode(
    'def foo(:\n  pass',
    "python"
  );
  const output = parseOutput(response);

  assert(output.exit_code !== 0, "Syntax error gives non-zero exit code");
  assert(output.stderr.length > 0, "Syntax error returns stderr");
  assert(
    output.stderr.includes("SyntaxError") || output.stderr.includes("invalid syntax"),
    "Stderr contains syntax error message"
  );
}

async function testToolDescription() {
  console.log("\n--- Test: Tool description under 100 words ---");
  const response = await callServer({
    method: "tools/list",
    params: {},
  });

  const tools = response.result.tools;
  assert(tools.length === 1, "Server exposes exactly one tool");
  assert(tools[0].name === "execute_code", "Tool is named execute_code");

  const desc = tools[0].description;
  const wordCount = desc.split(/\s+/).length;
  assert(wordCount < 100, `Tool description is ${wordCount} words (< 100)`);
}

// --- Runner ---

async function runTests() {
  console.log("=== exec-server.js integration tests ===\n");

  // Clean up old log file
  try {
    await rm(LOG_FILE, { force: true });
  } catch {
    // Fine if it doesn't exist
  }

  const tests = [
    testBashExecution,
    testPythonExecution,
    testPythonMultiline,
    testStructuredOutput,
    testNonZeroExitCode,
    testHardTimeout,
    testStrippedEnvHome,
    testStrippedEnvApiKey,
    testIsolatedWorkingDirectory,
    testSyntaxError,
    testToolDescription,
    testSessionLogger,
    testNetworkIsolation,
  ];

  for (const test of tests) {
    try {
      await test();
    } catch (err) {
      failed++;
      failures.push(`${test.name}: ${err.message}`);
      console.log(`  ERROR in ${test.name}: ${err.message}`);
    }
  }

  console.log(`\n=== Results: ${passed} passed, ${failed} failed ===`);
  if (failures.length > 0) {
    console.log("\nFailures:");
    for (const f of failures) {
      console.log(`  - ${f}`);
    }
  }

  process.exit(failed > 0 ? 1 : 0);
}

runTests();
