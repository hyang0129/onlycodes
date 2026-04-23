#!/usr/bin/env node

/**
 * Unit tests for interceptor.js
 *
 * Run: node --test test/test-interceptor.js
 */

import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  checkContent,
  checkDispatch,
  _resetRulesCache,
} from "../exec_server/interceptor.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(__dirname, "..");
const SHIPPED_CONFIG = join(REPO_ROOT, "exec_server", "passthrough-config.json");

// Reset cached rules before each test so config-path overrides work cleanly.
beforeEach(() => {
  _resetRulesCache();
});

// --- checkContent: surface = execute_code --------------------------------

test("checkContent: blocks bash code containing 'gh ' (gh followed by space)", () => {
  const result = checkContent("gh status", SHIPPED_CONFIG);
  assert.ok(result !== null, "expected a blocked result");
  assert.equal(result.blocked, true);
  assert.ok(
    typeof result.message === "string" && result.message.length > 0,
    "blocked result has a non-empty message",
  );
});

test("checkContent: blocks bash code containing 'gh\\t' (gh followed by tab)", () => {
  const result = checkContent("gh\tauth status", SHIPPED_CONFIG);
  assert.ok(result !== null, "expected a blocked result");
  assert.equal(result.blocked, true);
});

test("checkContent: blocks bash code where gh is at end of line (word boundary)", () => {
  const result = checkContent("which gh", SHIPPED_CONFIG);
  assert.ok(result !== null, "expected a blocked result");
  assert.equal(result.blocked, true);
});

test("checkContent: allows bash code that does not contain 'gh'", () => {
  const result = checkContent("echo hello world", SHIPPED_CONFIG);
  assert.equal(result, null, "expected null (allowed)");
});

test("checkContent: allows bash code with 'github' (word boundary — \\bgh\\b must NOT match 'github')", () => {
  const result = checkContent(
    "curl https://api.github.com/repos",
    SHIPPED_CONFIG,
  );
  assert.equal(
    result,
    null,
    "expected null (allowed) — 'github' must not trigger the \\bgh\\b rule",
  );
});

test("checkContent: allows Python code without 'gh'", () => {
  const result = checkContent(
    "import os\nprint(os.getcwd())",
    SHIPPED_CONFIG,
  );
  assert.equal(result, null);
});

test("checkContent: blocked result contains a message string", () => {
  const result = checkContent("gh pr list", SHIPPED_CONFIG);
  assert.ok(result !== null);
  assert.ok(
    typeof result.message === "string",
    "message must be a string",
  );
  assert.ok(result.message.length > 0, "message must be non-empty");
});

// --- checkDispatch: surface = dispatch -----------------------------------

test("checkDispatch: blocks 'delete_repo'", () => {
  const result = checkDispatch("delete_repo", SHIPPED_CONFIG);
  assert.ok(result !== null, "expected a blocked result");
  assert.equal(result.blocked, true);
  assert.ok(
    typeof result.message === "string" && result.message.length > 0,
    "blocked result has a non-empty message",
  );
});

test("checkDispatch: allows 'create_pr'", () => {
  const result = checkDispatch("create_pr", SHIPPED_CONFIG);
  assert.equal(result, null, "expected null (allowed)");
});

test("checkDispatch: allows 'list_repos'", () => {
  const result = checkDispatch("list_repos", SHIPPED_CONFIG);
  assert.equal(result, null, "expected null (allowed)");
});

test("checkDispatch: allows unknown tool names (only exact deny-list matches block)", () => {
  const result = checkDispatch("some_unknown_tool", SHIPPED_CONFIG);
  assert.equal(result, null);
});

test("checkDispatch: 'delete_repo' result has blocked=true", () => {
  const result = checkDispatch("delete_repo", SHIPPED_CONFIG);
  assert.ok(result !== null);
  assert.equal(result.blocked, true);
});

// --- return shape verification -------------------------------------------

test("checkContent: allowed result is exactly null", () => {
  const result = checkContent("python3 script.py", SHIPPED_CONFIG);
  assert.strictEqual(result, null);
});

test("checkDispatch: allowed result is exactly null", () => {
  const result = checkDispatch("create_issue", SHIPPED_CONFIG);
  assert.strictEqual(result, null);
});
