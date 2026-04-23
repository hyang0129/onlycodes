/**
 * config-loader.js — Validated loader for passthrough-config.json
 *
 * Exports:
 *   - loadConfig(configPath)      Reads, parses, validates the config file.
 *                                 Returns a normalized object with { subMcpServers, interceptRules }.
 *                                 Throws an Error with an actionable message on ANY malformation.
 *   - getBridgeSocketPath()       Returns the Unix domain socket path for the
 *                                 mcp_bridge <-> bridge-server link. Honors the
 *                                 ONLYCODES_BRIDGE_SOCK env var; otherwise falls back
 *                                 to a per-PID default `/tmp/onlycodes-bridge-${pid}.sock`.
 *                                 (ADR-001 Decision 2 / EPIC_13_ADR.md Decision 2.)
 *
 * The shipped config (`passthrough-config.json` at the repo root) is the source of
 * truth for sub-MCP server definitions and interception rules. The loader fails
 * fast on malformed input — consumers (interceptor.js, sub-mcp-manager.js,
 * bridge-server.js) should NOT attempt to recover from a bad config, because
 * silently running without interception rules is a security regression.
 *
 * UDS framing contract (documented here for cross-reference with mcp_bridge.py
 * and bridge-server.js):
 *   - Newline-delimited JSON (NDJSON). One JSON object per line, '\n' terminated.
 *   - UTF-8 on the wire.
 *   - Senders use JSON.stringify(obj) + '\n' (or json.dumps(obj) + '\n' in Python).
 *   - Receivers buffer until '\n', strip it, then parse.
 *   - Standard JSON encoders guarantee no raw '\n' inside payloads.
 *   - See EPIC_13_ADR.md Decision 1.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, isAbsolute } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const DEFAULT_CONFIG_PATH = join(__dirname, "passthrough-config.json");

const VALID_SURFACES = new Set(["execute_code", "dispatch"]);

/**
 * Validate a single sub-MCP server entry. Throws with a descriptive message
 * including the array index on any problem.
 */
function validateSubMcpServer(entry, index) {
  const label = `subMcpServers[${index}]`;
  if (entry === null || typeof entry !== "object" || Array.isArray(entry)) {
    throw new Error(
      `passthrough-config: ${label} must be an object, got ${Array.isArray(entry) ? "array" : typeof entry}`,
    );
  }
  if (typeof entry.name !== "string" || entry.name.length === 0) {
    throw new Error(
      `passthrough-config: ${label}.name must be a non-empty string`,
    );
  }
  if (typeof entry.command !== "string" || entry.command.length === 0) {
    throw new Error(
      `passthrough-config: ${label}.command must be a non-empty string (server "${entry.name}")`,
    );
  }
  if (!Array.isArray(entry.args)) {
    throw new Error(
      `passthrough-config: ${label}.args must be an array (server "${entry.name}")`,
    );
  }
  for (let i = 0; i < entry.args.length; i++) {
    if (typeof entry.args[i] !== "string") {
      throw new Error(
        `passthrough-config: ${label}.args[${i}] must be a string (server "${entry.name}")`,
      );
    }
  }
  if (!Array.isArray(entry.env)) {
    throw new Error(
      `passthrough-config: ${label}.env must be an array of env var NAMES (server "${entry.name}")`,
    );
  }
  for (let i = 0; i < entry.env.length; i++) {
    if (typeof entry.env[i] !== "string" || entry.env[i].length === 0) {
      throw new Error(
        `passthrough-config: ${label}.env[${i}] must be a non-empty string (server "${entry.name}")`,
      );
    }
  }
}

/**
 * Validate a single interception rule entry. Throws with a descriptive message
 * including the array index on any problem.
 */
function validateInterceptRule(rule, index) {
  const label = `interceptRules[${index}]`;
  if (rule === null || typeof rule !== "object" || Array.isArray(rule)) {
    throw new Error(
      `passthrough-config: ${label} must be an object, got ${Array.isArray(rule) ? "array" : typeof rule}`,
    );
  }
  if (typeof rule.surface !== "string" || !VALID_SURFACES.has(rule.surface)) {
    throw new Error(
      `passthrough-config: ${label}.surface must be one of ${[...VALID_SURFACES].join(", ")}, got ${JSON.stringify(rule.surface)}`,
    );
  }
  if (typeof rule.message !== "string" || rule.message.length === 0) {
    throw new Error(
      `passthrough-config: ${label}.message must be a non-empty string`,
    );
  }
  if (rule.surface === "execute_code") {
    if (typeof rule.pattern !== "string" || rule.pattern.length === 0) {
      throw new Error(
        `passthrough-config: ${label}.pattern must be a non-empty regex string for surface 'execute_code'`,
      );
    }
    // Compile to catch bad regex at load time rather than at first call.
    try {
      new RegExp(rule.pattern);
    } catch (err) {
      throw new Error(
        `passthrough-config: ${label}.pattern is not a valid regex: ${err.message}`,
      );
    }
  } else if (rule.surface === "dispatch") {
    if (typeof rule.tool !== "string" || rule.tool.length === 0) {
      throw new Error(
        `passthrough-config: ${label}.tool must be a non-empty string for surface 'dispatch'`,
      );
    }
  }
}

/**
 * Load, parse, and validate passthrough-config.json. Fails fast with a clear
 * message if the file is missing, not valid JSON, or does not match the schema.
 *
 * @param {string} [configPath] Absolute or repo-relative path. Defaults to the
 *   shipped `passthrough-config.json` next to this module.
 * @returns {{ subMcpServers: Array, interceptRules: Array }} Normalized config
 *   (the `_schema` documentation field, if present, is stripped).
 */
export function loadConfig(configPath = DEFAULT_CONFIG_PATH) {
  const resolvedPath = isAbsolute(configPath)
    ? configPath
    : join(__dirname, configPath);

  let raw;
  try {
    raw = readFileSync(resolvedPath, "utf8");
  } catch (err) {
    throw new Error(
      `passthrough-config: failed to read config at ${resolvedPath}: ${err.message}`,
    );
  }

  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (err) {
    throw new Error(
      `passthrough-config: ${resolvedPath} is not valid JSON: ${err.message}`,
    );
  }

  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(
      `passthrough-config: top-level value at ${resolvedPath} must be a JSON object`,
    );
  }

  if (!Array.isArray(parsed.subMcpServers)) {
    throw new Error(
      `passthrough-config: 'subMcpServers' must be an array (at ${resolvedPath})`,
    );
  }
  if (!Array.isArray(parsed.interceptRules)) {
    throw new Error(
      `passthrough-config: 'interceptRules' must be an array (at ${resolvedPath})`,
    );
  }

  const seenNames = new Set();
  for (let i = 0; i < parsed.subMcpServers.length; i++) {
    const entry = parsed.subMcpServers[i];
    validateSubMcpServer(entry, i);
    if (seenNames.has(entry.name)) {
      throw new Error(
        `passthrough-config: duplicate subMcpServers name "${entry.name}" at index ${i}`,
      );
    }
    seenNames.add(entry.name);
  }

  for (let i = 0; i < parsed.interceptRules.length; i++) {
    validateInterceptRule(parsed.interceptRules[i], i);
  }

  return {
    subMcpServers: parsed.subMcpServers,
    interceptRules: parsed.interceptRules,
  };
}

/**
 * Return the Unix domain socket path for the bridge link.
 *
 * Precedence:
 *   1. `ONLYCODES_BRIDGE_SOCK` env var, if set (and non-empty).
 *   2. Per-PID default `/tmp/onlycodes-bridge-${process.pid}.sock`.
 *
 * The per-PID default prevents socket collisions when parallel `swebench run`
 * instances each spawn their own `exec-server.js`. The env-var override is used
 * by tests (to get a predictable path), by Docker overlays, and — critically —
 * by `exec-server.js` to propagate the same path into every `execute_code`
 * subprocess so `mcp_bridge.py` can connect to the right bridge.
 *
 * See EPIC_13_ADR.md Decision 2.
 *
 * @returns {string} Absolute socket path.
 */
export function getBridgeSocketPath() {
  const fromEnv = process.env.ONLYCODES_BRIDGE_SOCK;
  if (typeof fromEnv === "string" && fromEnv.length > 0) {
    return fromEnv;
  }
  return `/tmp/onlycodes-bridge-${process.pid}.sock`;
}
