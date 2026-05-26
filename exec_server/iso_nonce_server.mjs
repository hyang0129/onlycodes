#!/usr/bin/env node
/**
 * iso_nonce_server.mjs — minimal MCP stub server for prompt-cache isolation.
 *
 * Purpose:
 *   When the harness is run with --cache-isolation, each (task, arm, run_idx)
 *   gets a deterministic 16-hex nonce. This server is registered in codex's
 *   per-task config.toml as an additional MCP server. It exposes a single
 *   tool whose name AND description embed that nonce.
 *
 *   Codex serialises the tool into the outbound Responses-API request's
 *   `tools[]` array. Because OpenAI's prompt cache treats `instructions + tools`
 *   together as the cache key, a one-tool delta (or a one-byte difference in
 *   any tool's description) misses cache for the entire prefix. By injecting
 *   a per-task-unique tool, we force a cold-cache first call for each task,
 *   eliminating cross-task cache leakage.
 *
 *   The tool itself is never expected to be called by the agent — its sole
 *   purpose is to byte-differ across tasks. If the agent does call it, we
 *   return a benign placeholder string.
 *
 * Nonce source:
 *   Read from env var ONLYCODES_ISOLATION_NONCE. If unset or empty, the
 *   server still starts (so a misconfigured run does not hang codex) but
 *   uses "unset" as the nonce. The harness should never start this server
 *   without setting the env var.
 *
 * This file lives alongside exec-server.js so npm install + the existing
 * `@modelcontextprotocol/sdk` dependency suffices. No build step needed —
 * it runs directly via `node exec_server/iso_nonce_server.mjs`.
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const NONCE = process.env.ONLYCODES_ISOLATION_NONCE || "unset";

const server = new Server(
  { name: "iso_nonce", version: "1.0.0" },
  { capabilities: { tools: {} } },
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      // The nonce is embedded in both the name and the description so the
      // serialised tools[] array bytes differ per task in two independent
      // ways. Either alone is sufficient for cache-breaking; both is belt-
      // and-braces against any field-stripping in codex's tool builder.
      name: `iso_nonce_${NONCE}`,
      description:
        `Cache-isolation marker tool for harness run id ${NONCE}. ` +
        `Do not call this tool; it exists only to force a per-task unique ` +
        `prompt prefix so OpenAI's prompt cache does not serve cross-task hits.`,
      inputSchema: {
        type: "object",
        properties: {},
        required: [],
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async () => ({
  content: [
    {
      type: "text",
      text:
        "iso_nonce is a cache-isolation marker tool. It performs no action. " +
        "Ignore this tool and use the other tools available to you.",
    },
  ],
}));

const transport = new StdioServerTransport();
await server.connect(transport);
