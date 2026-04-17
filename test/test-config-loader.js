#!/usr/bin/env node

/**
 * Unit tests for config-loader.js
 *
 * Run: node --test test/test-config-loader.js
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { loadConfig, getBridgeSocketPath } from "../config-loader.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(__dirname, "..");
const SHIPPED_CONFIG = join(REPO_ROOT, "passthrough-config.json");

/**
 * Create a temp dir with a named config file containing the given JSON.
 * Returns { dir, path, cleanup }.
 */
function mkTempConfig(content) {
  const dir = mkdtempSync(join(tmpdir(), "onlycodes-config-test-"));
  const path = join(dir, "passthrough-config.json");
  writeFileSync(path, content);
  return {
    dir,
    path,
    cleanup: () => rmSync(dir, { recursive: true, force: true }),
  };
}

// --- Shipped config ------------------------------------------------------

test("loadConfig: shipped passthrough-config.json loads without error", () => {
  const cfg = loadConfig(SHIPPED_CONFIG);
  assert.ok(Array.isArray(cfg.subMcpServers), "subMcpServers is an array");
  assert.ok(Array.isArray(cfg.interceptRules), "interceptRules is an array");
});

test("loadConfig: default path (no argument) resolves to shipped config", () => {
  const cfg = loadConfig();
  assert.ok(Array.isArray(cfg.subMcpServers));
  assert.ok(Array.isArray(cfg.interceptRules));
});

test("shipped config: contains github sub-MCP entry", () => {
  const cfg = loadConfig(SHIPPED_CONFIG);
  const github = cfg.subMcpServers.find((s) => s.name === "github");
  assert.ok(github, "github sub-MCP entry present");
  assert.equal(typeof github.command, "string");
  assert.ok(Array.isArray(github.args));
  assert.ok(Array.isArray(github.env));
  assert.ok(
    github.env.includes("GITHUB_TOKEN"),
    "github entry declares GITHUB_TOKEN in env passthrough list",
  );
});

test("shipped config: baseline \\bgh\\b content-scan deny rule present", () => {
  const cfg = loadConfig(SHIPPED_CONFIG);
  const ghRule = cfg.interceptRules.find(
    (r) => r.surface === "execute_code" && r.pattern === "\\bgh\\b",
  );
  assert.ok(ghRule, "\\bgh\\b content-scan deny rule present");
  assert.ok(
    typeof ghRule.message === "string" && ghRule.message.length > 0,
    "gh deny rule has a non-empty message",
  );
});

test("shipped config: baseline delete_repo dispatch deny rule present", () => {
  const cfg = loadConfig(SHIPPED_CONFIG);
  const delRule = cfg.interceptRules.find(
    (r) => r.surface === "dispatch" && r.tool === "delete_repo",
  );
  assert.ok(delRule, "delete_repo dispatch deny rule present");
  assert.ok(
    typeof delRule.message === "string" && delRule.message.length > 0,
    "delete_repo deny rule has a non-empty message",
  );
});

// --- Malformed inputs ----------------------------------------------------

test("loadConfig: missing file throws actionable message", () => {
  assert.throws(
    () => loadConfig("/tmp/onlycodes-nonexistent-config-xyz.json"),
    /failed to read config/,
  );
});

test("loadConfig: invalid JSON throws with 'not valid JSON'", () => {
  const t = mkTempConfig("{ this is not json ");
  try {
    assert.throws(() => loadConfig(t.path), /not valid JSON/);
  } finally {
    t.cleanup();
  }
});

test("loadConfig: top-level array is rejected", () => {
  const t = mkTempConfig("[]");
  try {
    assert.throws(() => loadConfig(t.path), /must be a JSON object/);
  } finally {
    t.cleanup();
  }
});

test("loadConfig: missing subMcpServers throws", () => {
  const t = mkTempConfig(JSON.stringify({ interceptRules: [] }));
  try {
    assert.throws(() => loadConfig(t.path), /'subMcpServers' must be an array/);
  } finally {
    t.cleanup();
  }
});

test("loadConfig: missing interceptRules throws", () => {
  const t = mkTempConfig(JSON.stringify({ subMcpServers: [] }));
  try {
    assert.throws(
      () => loadConfig(t.path),
      /'interceptRules' must be an array/,
    );
  } finally {
    t.cleanup();
  }
});

test("loadConfig: sub-MCP server missing name throws with field path", () => {
  const t = mkTempConfig(
    JSON.stringify({
      subMcpServers: [{ command: "echo", args: [], env: [] }],
      interceptRules: [],
    }),
  );
  try {
    assert.throws(
      () => loadConfig(t.path),
      /subMcpServers\[0\]\.name must be a non-empty string/,
    );
  } finally {
    t.cleanup();
  }
});

test("loadConfig: sub-MCP server with non-array args throws", () => {
  const t = mkTempConfig(
    JSON.stringify({
      subMcpServers: [
        { name: "x", command: "echo", args: "not-an-array", env: [] },
      ],
      interceptRules: [],
    }),
  );
  try {
    assert.throws(
      () => loadConfig(t.path),
      /subMcpServers\[0\]\.args must be an array/,
    );
  } finally {
    t.cleanup();
  }
});

test("loadConfig: duplicate sub-MCP server names throws", () => {
  const t = mkTempConfig(
    JSON.stringify({
      subMcpServers: [
        { name: "dup", command: "echo", args: [], env: [] },
        { name: "dup", command: "echo", args: [], env: [] },
      ],
      interceptRules: [],
    }),
  );
  try {
    assert.throws(
      () => loadConfig(t.path),
      /duplicate subMcpServers name "dup"/,
    );
  } finally {
    t.cleanup();
  }
});

test("loadConfig: intercept rule with bad surface throws", () => {
  const t = mkTempConfig(
    JSON.stringify({
      subMcpServers: [],
      interceptRules: [{ surface: "nope", message: "x", pattern: "y" }],
    }),
  );
  try {
    assert.throws(() => loadConfig(t.path), /\.surface must be one of/);
  } finally {
    t.cleanup();
  }
});

test("loadConfig: execute_code rule missing pattern throws", () => {
  const t = mkTempConfig(
    JSON.stringify({
      subMcpServers: [],
      interceptRules: [{ surface: "execute_code", message: "x" }],
    }),
  );
  try {
    assert.throws(
      () => loadConfig(t.path),
      /\.pattern must be a non-empty regex string/,
    );
  } finally {
    t.cleanup();
  }
});

test("loadConfig: execute_code rule with invalid regex throws", () => {
  const t = mkTempConfig(
    JSON.stringify({
      subMcpServers: [],
      interceptRules: [
        { surface: "execute_code", pattern: "([unclosed", message: "x" },
      ],
    }),
  );
  try {
    assert.throws(() => loadConfig(t.path), /is not a valid regex/);
  } finally {
    t.cleanup();
  }
});

test("loadConfig: dispatch rule missing tool throws", () => {
  const t = mkTempConfig(
    JSON.stringify({
      subMcpServers: [],
      interceptRules: [{ surface: "dispatch", message: "x" }],
    }),
  );
  try {
    assert.throws(
      () => loadConfig(t.path),
      /\.tool must be a non-empty string/,
    );
  } finally {
    t.cleanup();
  }
});

test("loadConfig: intercept rule missing message throws", () => {
  const t = mkTempConfig(
    JSON.stringify({
      subMcpServers: [],
      interceptRules: [{ surface: "dispatch", tool: "x" }],
    }),
  );
  try {
    assert.throws(
      () => loadConfig(t.path),
      /\.message must be a non-empty string/,
    );
  } finally {
    t.cleanup();
  }
});

// --- getBridgeSocketPath -------------------------------------------------

test("getBridgeSocketPath: returns ONLYCODES_BRIDGE_SOCK when set", () => {
  const prev = process.env.ONLYCODES_BRIDGE_SOCK;
  try {
    process.env.ONLYCODES_BRIDGE_SOCK = "/tmp/custom-test.sock";
    assert.equal(getBridgeSocketPath(), "/tmp/custom-test.sock");
  } finally {
    if (prev === undefined) delete process.env.ONLYCODES_BRIDGE_SOCK;
    else process.env.ONLYCODES_BRIDGE_SOCK = prev;
  }
});

test("getBridgeSocketPath: per-PID default when env var unset", () => {
  const prev = process.env.ONLYCODES_BRIDGE_SOCK;
  try {
    delete process.env.ONLYCODES_BRIDGE_SOCK;
    const expected = `/tmp/onlycodes-bridge-${process.pid}.sock`;
    assert.equal(getBridgeSocketPath(), expected);
  } finally {
    if (prev !== undefined) process.env.ONLYCODES_BRIDGE_SOCK = prev;
  }
});

test("getBridgeSocketPath: per-PID default when env var is empty string", () => {
  const prev = process.env.ONLYCODES_BRIDGE_SOCK;
  try {
    process.env.ONLYCODES_BRIDGE_SOCK = "";
    const expected = `/tmp/onlycodes-bridge-${process.pid}.sock`;
    assert.equal(getBridgeSocketPath(), expected);
  } finally {
    if (prev === undefined) delete process.env.ONLYCODES_BRIDGE_SOCK;
    else process.env.ONLYCODES_BRIDGE_SOCK = prev;
  }
});
