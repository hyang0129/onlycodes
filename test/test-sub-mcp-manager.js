#!/usr/bin/env node

/**
 * Unit tests for sub-mcp-manager.js
 *
 * Run: node --test test/test-sub-mcp-manager.js
 *
 * These tests do NOT require a live sub-MCP server. They verify:
 *   1. buildSubMcpEnv() credential isolation (strips non-declared vars)
 *   2. buildSubMcpEnv() passes through declared vars (e.g. GITHUB_TOKEN)
 *   3. buildSubMcpEnv() passes through safe system vars (PATH, HOME, etc.)
 *   4. callTool() returns a structured error for an unknown server
 *   5. getSchema() returns a structured error for an unknown server
 *   6. callTool() returns a structured error (never throws) when server is unreachable
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { buildSubMcpEnv } from "../sub-mcp-manager.js";
import manager from "../sub-mcp-manager.js";

// ---------------------------------------------------------------------------
// buildSubMcpEnv tests
// ---------------------------------------------------------------------------

test("buildSubMcpEnv: strips credential vars not in serverConfig.env", () => {
  // Temporarily set a secret env var that is NOT in serverConfig.env
  const prev = process.env.SECRET_TOKEN;
  try {
    process.env.SECRET_TOKEN = "super-secret-value";
    const env = buildSubMcpEnv({ env: [] });
    assert.ok(
      !Object.prototype.hasOwnProperty.call(env, "SECRET_TOKEN"),
      "SECRET_TOKEN must not appear in stripped env",
    );
  } finally {
    if (prev === undefined) delete process.env.SECRET_TOKEN;
    else process.env.SECRET_TOKEN = prev;
  }
});

test("buildSubMcpEnv: strips GITHUB_TOKEN when not declared in serverConfig.env", () => {
  const prev = process.env.GITHUB_TOKEN;
  try {
    process.env.GITHUB_TOKEN = "gh_test_credential_xyz";
    const env = buildSubMcpEnv({ env: [] }); // no vars declared
    assert.ok(
      !Object.prototype.hasOwnProperty.call(env, "GITHUB_TOKEN"),
      "GITHUB_TOKEN must not appear when not declared in serverConfig.env",
    );
  } finally {
    if (prev === undefined) delete process.env.GITHUB_TOKEN;
    else process.env.GITHUB_TOKEN = prev;
  }
});

test("buildSubMcpEnv: passes GITHUB_TOKEN when declared in serverConfig.env", () => {
  const prev = process.env.GITHUB_TOKEN;
  try {
    process.env.GITHUB_TOKEN = "gh_test_token_abc123";
    const env = buildSubMcpEnv({ env: ["GITHUB_TOKEN"] });
    assert.equal(
      env.GITHUB_TOKEN,
      "gh_test_token_abc123",
      "GITHUB_TOKEN must appear when declared in serverConfig.env",
    );
  } finally {
    if (prev === undefined) delete process.env.GITHUB_TOKEN;
    else process.env.GITHUB_TOKEN = prev;
  }
});

test("buildSubMcpEnv: passes multiple declared vars independently", () => {
  const prevGithub = process.env.GITHUB_TOKEN;
  const prevSecret = process.env.SECRET_TOKEN;
  const prevOther = process.env.OTHER_SAFE_VAR;
  try {
    process.env.GITHUB_TOKEN = "gh_token";
    process.env.SECRET_TOKEN = "secret_value"; // not declared
    process.env.OTHER_SAFE_VAR = "other_value"; // declared
    const env = buildSubMcpEnv({ env: ["GITHUB_TOKEN", "OTHER_SAFE_VAR"] });
    assert.equal(env.GITHUB_TOKEN, "gh_token", "GITHUB_TOKEN included when declared");
    assert.equal(env.OTHER_SAFE_VAR, "other_value", "OTHER_SAFE_VAR included when declared");
    assert.ok(
      !Object.prototype.hasOwnProperty.call(env, "SECRET_TOKEN"),
      "SECRET_TOKEN absent when not declared",
    );
  } finally {
    if (prevGithub === undefined) delete process.env.GITHUB_TOKEN;
    else process.env.GITHUB_TOKEN = prevGithub;
    if (prevSecret === undefined) delete process.env.SECRET_TOKEN;
    else process.env.SECRET_TOKEN = prevSecret;
    if (prevOther === undefined) delete process.env.OTHER_SAFE_VAR;
    else process.env.OTHER_SAFE_VAR = prevOther;
  }
});

test("buildSubMcpEnv: passes through PATH when set in process env", () => {
  // PATH is a safe var and should always be passed through if present
  if (process.env.PATH) {
    const env = buildSubMcpEnv({ env: [] });
    assert.equal(
      env.PATH,
      process.env.PATH,
      "PATH must be present in stripped env (needed to find binaries)",
    );
  }
});

test("buildSubMcpEnv: passes through HOME when set in process env", () => {
  if (process.env.HOME) {
    const env = buildSubMcpEnv({ env: [] });
    assert.equal(
      env.HOME,
      process.env.HOME,
      "HOME must be present in stripped env",
    );
  }
});

test("buildSubMcpEnv: handles missing serverConfig.env gracefully (defaults to [])", () => {
  const prev = process.env.GITHUB_TOKEN;
  try {
    process.env.GITHUB_TOKEN = "gh_should_not_appear";
    // serverConfig has no env field at all
    const env = buildSubMcpEnv({});
    assert.ok(
      !Object.prototype.hasOwnProperty.call(env, "GITHUB_TOKEN"),
      "No credential leaks when serverConfig.env is absent",
    );
  } finally {
    if (prev === undefined) delete process.env.GITHUB_TOKEN;
    else process.env.GITHUB_TOKEN = prev;
  }
});

test("buildSubMcpEnv: does not include declared var when it is not in process.env", () => {
  const prev = process.env.NONEXISTENT_VAR_XYZ_ABC;
  try {
    delete process.env.NONEXISTENT_VAR_XYZ_ABC;
    const env = buildSubMcpEnv({ env: ["NONEXISTENT_VAR_XYZ_ABC"] });
    assert.ok(
      !Object.prototype.hasOwnProperty.call(env, "NONEXISTENT_VAR_XYZ_ABC"),
      "Declared var absent from process.env must not appear in result",
    );
  } finally {
    if (prev !== undefined) process.env.NONEXISTENT_VAR_XYZ_ABC = prev;
  }
});

// ---------------------------------------------------------------------------
// SubMcpManager error-handling tests (no live server required)
// ---------------------------------------------------------------------------

test("manager.callTool: returns structured error for unknown server name", async () => {
  const result = await manager.callTool("nonexistent-server-xyz", "some_tool", {});
  assert.ok(result !== null && typeof result === "object", "result is an object");
  assert.equal(result.error, true, "result.error must be true");
  assert.ok(
    typeof result.message === "string" && result.message.length > 0,
    "result.message must be a non-empty string",
  );
  assert.match(
    result.message,
    /nonexistent-server-xyz/,
    "error message should mention the server name",
  );
});

test("manager.getSchema: returns structured error for unknown server name", async () => {
  const result = await manager.getSchema("nonexistent-server-xyz", "some_tool");
  assert.ok(result !== null && typeof result === "object", "result is an object");
  assert.equal(result.error, true, "result.error must be true");
  assert.ok(
    typeof result.message === "string" && result.message.length > 0,
    "result.message must be a non-empty string",
  );
});

test("manager.callTool: never throws — returns structured error for unreachable server", async () => {
  // Use a server config that points to a non-existent command to simulate
  // an unreachable server. We test that no exception propagates out.
  let threw = false;
  let result;
  try {
    // The github server is defined in the config but @github/mcp is not
    // installed in this test environment, so the spawn will fail.
    // If it somehow succeeds (CI has the package), that's also fine —
    // we just check no exception is thrown.
    result = await manager.callTool("github", "some_tool", {});
  } catch (err) {
    threw = true;
  }
  assert.equal(threw, false, "callTool must not throw — must return structured error");
  // result may be { error: true, message: ... } or a real response —
  // both are acceptable (the server may or may not be installed)
  if (result && result.error) {
    assert.ok(
      typeof result.message === "string",
      "structured error must have a message string",
    );
  }
});

test("manager.getSchema: never throws — returns structured error for unreachable server", async () => {
  let threw = false;
  let result;
  try {
    result = await manager.getSchema("github", "some_tool");
  } catch (err) {
    threw = true;
  }
  assert.equal(threw, false, "getSchema must not throw — must return structured error");
  if (result && result.error) {
    assert.ok(
      typeof result.message === "string",
      "structured error must have a message string",
    );
  }
});
