/**
 * bridge-server.js — Unix socket server routing mcp_bridge.py calls
 *
 * Listens on a Unix domain socket at getBridgeSocketPath() and serves
 * NDJSON (newline-delimited JSON) requests from mcp_bridge.py clients.
 *
 * Supported request methods:
 *   - call:       { method: "call", server, tool, args? }
 *                 Runs through interceptor.checkDispatch() first. If denied,
 *                 returns { error: true, message }. Otherwise forwards to
 *                 manager.callTool(server, tool, args).
 *   - get_schema: { method: "get_schema", server, tool }
 *                 Forwarded directly to manager.getSchema(server, tool).
 *
 * Protocol (ADR Decision 1 — NDJSON):
 *   Each message is JSON.stringify(obj) + "\n". Receivers buffer until "\n".
 *
 * Socket path (ADR Decision 2 — per-PID with env override):
 *   getBridgeSocketPath() → ONLYCODES_BRIDGE_SOCK env var or
 *   /tmp/onlycodes-bridge-${pid}.sock
 *
 * Exports:
 *   start()         Starts the server. Returns the net.Server instance.
 *                   Also exposes server.sockPath for callers that need the path.
 *   stop(server)    Closes the server and removes the socket file.
 */

import net from "node:net";
import fs from "node:fs";
import { checkDispatch } from "./interceptor.js";
import manager from "./sub-mcp-manager.js";
import { getBridgeSocketPath } from "./config-loader.js";

/**
 * Start the bridge Unix socket server.
 *
 * @returns {net.Server} The running server (with .sockPath set).
 */
export function start() {
  const sockPath = getBridgeSocketPath();

  // Remove any stale socket file from a previous run / crash
  try {
    fs.unlinkSync(sockPath);
  } catch {
    // File didn't exist — that's fine
  }

  const server = net.createServer((socket) => {
    let buf = "";

    socket.on("data", (chunk) => {
      buf += chunk.toString("utf8");
      const lines = buf.split("\n");
      buf = lines.pop(); // keep the (possibly empty) incomplete trailing piece
      for (const line of lines) {
        if (!line.trim()) continue;
        handleRequest(socket, line);
      }
    });

    // Silently ignore client disconnects / EPIPE — they are not server errors
    socket.on("error", () => {});
  });

  server.listen(sockPath, () => {
    // Socket is ready; nothing to log here — callers can check server.listening
  });

  // Expose the path so callers (e.g. exec-server.js, tests) can read it
  server.sockPath = sockPath;

  // Clean up the socket file on graceful shutdown signals
  const cleanup = () => {
    server.close();
    try {
      fs.unlinkSync(sockPath);
    } catch {
      // Already gone — ignore
    }
  };

  process.on("SIGTERM", cleanup);
  process.on("SIGINT", cleanup);

  return server;
}

/**
 * Stop a running bridge server and remove its socket file.
 *
 * @param {net.Server} server - The server instance returned by start().
 */
export function stop(server) {
  const sockPath = getBridgeSocketPath();
  server.close();
  try {
    fs.unlinkSync(sockPath);
  } catch {
    // Already gone — ignore
  }
}

/**
 * Handle a single NDJSON request line on a connected socket.
 *
 * Always writes exactly one NDJSON line back. Never throws.
 *
 * @param {net.Socket} socket
 * @param {string} line - A single (complete) JSON string with no trailing newline.
 */
async function handleRequest(socket, line) {
  let req;
  try {
    req = JSON.parse(line);
  } catch {
    write(socket, { error: true, message: "Invalid JSON request" });
    return;
  }

  try {
    if (req.method === "call") {
      const denied = checkDispatch(req.tool);
      if (denied) {
        write(socket, { error: true, message: denied.message });
        return;
      }
      const result = await manager.callTool(req.server, req.tool, req.args || {});
      write(socket, result);
    } else if (req.method === "get_schema") {
      const result = await manager.getSchema(req.server, req.tool);
      write(socket, result);
    } else {
      write(socket, {
        error: true,
        message: `Unknown method: ${req.method}`,
      });
    }
  } catch (err) {
    write(socket, { error: true, message: err.message });
  }
}

/**
 * Write a single NDJSON response line to a socket.
 * Silently ignores write errors (e.g. client already disconnected).
 *
 * @param {net.Socket} socket
 * @param {unknown} obj - Serialisable JS value.
 */
function write(socket, obj) {
  try {
    socket.write(JSON.stringify(obj) + "\n");
  } catch {
    // Client disconnected before the response was sent — ignore
  }
}
