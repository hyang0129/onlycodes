/**
 * interceptor.js — Config-driven middleware chain for deny-list enforcement
 *
 * Enforces rules on two surfaces:
 *   1. execute_code content scanning: regex deny-list on bash/python source
 *   2. sub-MCP dispatch: tool-name deny-list before forwarding to sub-MCP manager
 *
 * Rules are loaded from passthrough-config.json via config-loader.js.
 * Adding or modifying rules requires only a JSON change — no code edits.
 *
 * Exports:
 *   checkContent(code)         Check execute_code source against the deny-list.
 *                              Returns null if allowed, or { blocked: true, message: string } if denied.
 *   checkDispatch(toolName)    Check a sub-MCP tool dispatch against the deny-list.
 *                              Returns null if allowed, or { blocked: true, message: string } if denied.
 */

import { loadConfig } from "./config-loader.js";

let _rules = null;

/**
 * Load and cache the interception rules from passthrough-config.json.
 * On first call, the config is read and validated; subsequent calls use the cache.
 *
 * @param {string} [configPath] Optional path override (used by tests).
 * @returns {Array} The interceptRules array from the config.
 */
function getRules(configPath = undefined) {
  if (!_rules) {
    const config = configPath ? loadConfig(configPath) : loadConfig();
    _rules = config.interceptRules;
  }
  return _rules;
}

/**
 * Reset the cached rules. Exposed for testing so tests can inject a custom
 * config path on each test without stale state leaking between test cases.
 */
export function _resetRulesCache() {
  _rules = null;
}

/**
 * Check execute_code source code against the content-scan deny-list.
 *
 * Each rule with surface === 'execute_code' has a `pattern` (regex string).
 * The rules are checked in order; the first match wins.
 *
 * @param {string} code  The script source to check.
 * @param {string} [configPath]  Optional config path override (for tests).
 * @returns {null | { blocked: true, message: string }}
 *   null if the code is allowed; a blocked-result object if a rule fires.
 */
export function checkContent(code, configPath = undefined) {
  const rules = getRules(configPath).filter(
    (r) => r.surface === "execute_code",
  );
  for (const rule of rules) {
    const regex = new RegExp(rule.pattern);
    if (regex.test(code)) {
      return { blocked: true, message: rule.message };
    }
  }
  return null;
}

/**
 * Check a sub-MCP tool dispatch against the dispatch deny-list.
 *
 * Each rule with surface === 'dispatch' has a `tool` (exact tool name string).
 * The rules are checked in order; the first match wins.
 *
 * @param {string} toolName  The tool name about to be dispatched.
 * @param {string} [configPath]  Optional config path override (for tests).
 * @returns {null | { blocked: true, message: string }}
 *   null if the dispatch is allowed; a blocked-result object if a rule fires.
 */
export function checkDispatch(toolName, configPath = undefined) {
  const rules = getRules(configPath).filter((r) => r.surface === "dispatch");
  for (const rule of rules) {
    if (rule.tool === toolName) {
      return { blocked: true, message: rule.message };
    }
  }
  return null;
}
