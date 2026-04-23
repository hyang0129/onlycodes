/**
 * sub-mcp-manager.js — Sub-MCP server child process lifecycle manager
 *
 * Manages stdio child processes for each sub-MCP server defined in
 * passthrough-config.json. Uses the MCP SDK Client + StdioClientTransport
 * to speak the full MCP protocol over the child process's stdin/stdout.
 *
 * Key design decisions (from EPIC_13_ADR.md and EPIC_13_DECOMPOSITION.md):
 *   - Lazy init: child processes are spawned on first callTool invocation
 *   - Crash recovery: exponential backoff (1s, 2s, 4s, ... max 30s)
 *   - Credential isolation: buildSubMcpEnv() strips all credentials and
 *     adds back only the vars declared in serverConfig.env
 *   - Sub-MCP crashes NEVER propagate to callers — structured error returned
 *   - callTool and getSchema always return { error, message } on failure
 */

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { loadConfig } from "./config-loader.js";

// Safe environment variables that are not credentials and are needed for
// sub-MCP servers to function (e.g., find binaries, write temp files).
const SAFE_VARS = [
  "PATH",
  "HOME",
  "TMPDIR",
  "TEMP",
  "TMP",
  "NODE_PATH",
  "npm_config_cache",
  "SHELL",
  "TERM",
  "USER",
  "LOGNAME",
  "LANG",
  "LC_ALL",
  "LC_CTYPE",
  // npm/npx need these to locate global modules
  "npm_config_prefix",
  "npm_config_global_prefix",
  "XDG_CONFIG_HOME",
  "XDG_DATA_HOME",
  "XDG_CACHE_HOME",
];

/**
 * Build a stripped environment for a sub-MCP server child process.
 *
 * Starts from a safe subset of the main process env (only SAFE_VARS),
 * then adds back only the variables explicitly declared in serverConfig.env.
 * This ensures that credentials not listed in serverConfig.env are never
 * passed to the child process — even if they happen to be in the main env.
 *
 * @param {{ env?: string[] }} serverConfig - Sub-MCP server config entry
 * @returns {Record<string, string>} Sanitized environment object
 */
export function buildSubMcpEnv(serverConfig) {
  const stripped = {};

  // Pass through safe (non-credential) vars only
  for (const key of SAFE_VARS) {
    if (process.env[key] !== undefined) {
      stripped[key] = process.env[key];
    }
  }

  // Add only the explicitly declared vars for this server
  for (const varName of (serverConfig.env || [])) {
    if (process.env[varName] !== undefined) {
      stripped[varName] = process.env[varName];
    }
  }

  return stripped;
}

// Backoff configuration for crash recovery
const BACKOFF_INITIAL_MS = 1000;
const BACKOFF_MULTIPLIER = 2;
const BACKOFF_MAX_MS = 30000;

/**
 * Compute the next backoff delay in milliseconds using exponential backoff.
 *
 * @param {number} attempt - Zero-based attempt index (0 = first retry)
 * @returns {number} Delay in milliseconds, capped at BACKOFF_MAX_MS
 */
function computeBackoff(attempt) {
  const delay = BACKOFF_INITIAL_MS * Math.pow(BACKOFF_MULTIPLIER, attempt);
  return Math.min(delay, BACKOFF_MAX_MS);
}

/**
 * SubMcpManager — singleton class for managing sub-MCP server connections.
 *
 * Each sub-MCP server is a child process connected via the MCP stdio protocol
 * (StdioClientTransport). Servers are started lazily on first use and
 * restarted with exponential backoff on crash.
 */
class SubMcpManager {
  constructor() {
    // name -> ServerState
    this._servers = {};
    this._config = null;
  }

  /**
   * Load config lazily (once per manager lifetime).
   * @returns {{ subMcpServers: Array, interceptRules: Array }}
   */
  _getConfig() {
    if (!this._config) {
      this._config = loadConfig();
    }
    return this._config;
  }

  /**
   * Get the config entry for a named sub-MCP server.
   * @param {string} name
   * @returns {{ name: string, command: string, args: string[], env: string[] }}
   * @throws {Error} if the server name is not in the config
   */
  _getServerConfig(name) {
    const server = this._getConfig().subMcpServers.find((s) => s.name === name);
    if (!server) {
      throw new Error(`Unknown sub-MCP server: ${name}`);
    }
    return server;
  }

  /**
   * Get or initialize the server state object for a named server.
   * @param {string} name
   * @returns {ServerState}
   */
  _getServerState(name) {
    if (!this._servers[name]) {
      this._servers[name] = {
        client: null,
        transport: null,
        status: "disconnected", // "disconnected" | "connecting" | "connected" | "crashed"
        crashCount: 0,
        connectPromise: null,
      };
    }
    return this._servers[name];
  }

  /**
   * Ensure a sub-MCP server is connected, spawning it if necessary.
   * Uses a per-server connect mutex (connectPromise) to avoid double-init.
   *
   * On crash, waits for an exponential backoff delay before reconnecting.
   *
   * @param {string} name - Server name from passthrough-config.json
   * @returns {Promise<void>} Resolves when the client is ready to use
   * @throws {Error} if connection fails after the attempt
   */
  async _ensureConnected(name) {
    const state = this._getServerState(name);

    // Already connected
    if (state.status === "connected" && state.client) {
      return;
    }

    // Already connecting — wait on the existing promise
    if (state.status === "connecting" && state.connectPromise) {
      return state.connectPromise;
    }

    // Start a new connection attempt
    state.status = "connecting";
    state.connectPromise = this._doConnect(name, state);

    try {
      await state.connectPromise;
    } finally {
      state.connectPromise = null;
    }
  }

  /**
   * Internal: perform the actual spawn + MCP handshake.
   * Called from _ensureConnected when no existing connection is live.
   *
   * @param {string} name
   * @param {ServerState} state
   */
  async _doConnect(name, state) {
    // Exponential backoff on repeated crashes
    if (state.crashCount > 0) {
      const delay = computeBackoff(state.crashCount - 1);
      await new Promise((resolve) => setTimeout(resolve, delay));
    }

    const serverConfig = this._getServerConfig(name);
    const env = buildSubMcpEnv(serverConfig);

    // Close any existing transport/client before reconnecting
    if (state.transport) {
      try {
        await state.transport.close();
      } catch {
        // Ignore close errors on a crashed transport
      }
      state.transport = null;
      state.client = null;
    }

    const transport = new StdioClientTransport({
      command: serverConfig.command,
      args: serverConfig.args,
      env,
      stderr: "inherit", // surface sub-MCP stderr for debugging
    });

    const client = new Client(
      { name: "onlycodes-passthrough", version: "1.0.0" },
      { capabilities: {} },
    );

    // Detect crashes: when the transport closes unexpectedly, mark as crashed
    transport.onclose = () => {
      if (state.status === "connected") {
        state.status = "crashed";
        state.crashCount++;
        state.client = null;
        state.transport = null;
      }
    };

    transport.onerror = (err) => {
      // Log but don't throw — crash is handled via onclose
      // (stderr is already inherited, so the error details appear there)
      void err; // suppress lint warnings; error surfaces through onclose
    };

    try {
      await client.connect(transport);
    } catch (err) {
      state.status = "crashed";
      state.crashCount++;
      state.client = null;
      state.transport = null;
      throw new Error(`Failed to connect to sub-MCP server "${name}": ${err.message}`);
    }

    state.client = client;
    state.transport = transport;
    state.status = "connected";
  }

  /**
   * Call a tool on a named sub-MCP server.
   *
   * Ensures the server is connected (spawning lazily or recovering from crash),
   * then invokes the tool via the MCP protocol.
   *
   * If the server is unavailable or the call fails, returns a structured
   * error object — NEVER throws to the caller.
   *
   * @param {string} serverName - Sub-MCP server name (from passthrough-config.json)
   * @param {string} toolName - Tool name to invoke
   * @param {Record<string, unknown>} args - Tool arguments
   * @returns {Promise<{ error: true, message: string } | unknown>}
   *   On success: the tool result from the MCP server.
   *   On failure: { error: true, message: string }
   */
  async callTool(serverName, toolName, args) {
    try {
      await this._ensureConnected(serverName);
      const state = this._getServerState(serverName);
      if (!state.client) {
        return { error: true, message: `Sub-MCP server "${serverName}" is not available` };
      }
      const result = await state.client.callTool({ name: toolName, arguments: args });
      return result;
    } catch (err) {
      return { error: true, message: err.message };
    }
  }

  /**
   * Get the JSON schema for a specific tool on a named sub-MCP server.
   *
   * Ensures the server is connected, then calls listTools and finds the
   * matching entry. Returns the inputSchema from that entry.
   *
   * If the server is unavailable or the tool is not found, returns a
   * structured error object — NEVER throws to the caller.
   *
   * @param {string} serverName - Sub-MCP server name
   * @param {string} toolName - Tool name to look up
   * @returns {Promise<{ error: true, message: string } | object>}
   *   On success: the inputSchema object for the tool.
   *   On failure: { error: true, message: string }
   */
  async getSchema(serverName, toolName) {
    try {
      await this._ensureConnected(serverName);
      const state = this._getServerState(serverName);
      if (!state.client) {
        return { error: true, message: `Sub-MCP server "${serverName}" is not available` };
      }
      const { tools } = await state.client.listTools();
      const tool = tools.find((t) => t.name === toolName);
      if (!tool) {
        return { error: true, message: `Tool "${toolName}" not found on sub-MCP server "${serverName}"` };
      }
      return tool.inputSchema || {};
    } catch (err) {
      return { error: true, message: err.message };
    }
  }

  /**
   * Close all open sub-MCP connections. Useful for graceful shutdown.
   * Errors during close are swallowed — callers should not depend on clean
   * teardown in crash/signal scenarios.
   */
  async closeAll() {
    const closePromises = Object.entries(this._servers).map(async ([, state]) => {
      if (state.transport) {
        try {
          await state.transport.close();
        } catch {
          // Swallow — we're shutting down
        }
      }
      state.client = null;
      state.transport = null;
      state.status = "disconnected";
    });
    await Promise.allSettled(closePromises);
  }
}

// Singleton export — one manager per process
const manager = new SubMcpManager();
export default manager;
