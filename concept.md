# Code Mode: Applying Cloudflare's MCP Insight to Claude Code

## The Core Insight

Cloudflare's "Code Mode" observes that LLMs are better at *writing code* to call MCP tools than at calling them directly via function calling. The reason is simple: LLMs have seen millions of real-world TypeScript/Python projects but only small synthetic tool-calling training sets.

Standard agent loop:
```
LLM → tool_call → result → LLM → tool_call → result → LLM → ...
```

Code Mode loop:
```
LLM → writes script → sandbox executes → one final result → LLM
```

Every intermediate tool call is a full LLM forward pass. Code Mode collapses N tool calls into 1.

---

## Why This Applies to Claude Code

Claude Code's built-in `bash` tool accepts one command and returns one result. There's no way to express "run these 10 things and give me all results together." So Claude sequences them — one grep per round-trip — even when it already knows it needs all of them.

With an `execute_code` tool, Claude writes one script:

```python
results = {}
for f in files:
    results[f] = subprocess.run(['grep', 'keyword', f], capture_output=True).stdout
print(results)
```

One round-trip. Same information.

---

## Architecture

### Why You Can't Shadow Built-in Tools via MCP

Claude Code's built-in tools (`bash`, `read_file`, etc.) are hardcoded into the process, namespaced separately from MCP tools (`mcp__servername__toolname`). You can't override them with an MCP server of the same name — Claude sees both and prefers built-ins. Redirecting via tool results still costs a round-trip.

### Why MCP Servers Can't Talk to Each Other

MCP is strictly client → server. No server-to-server communication exists in the spec. Multi-source fan-out (e.g. grep across filesystem MCP + GitHub MCP) currently requires Claude to re-enter the neural network between each call.

### The Proxy Pattern

A Code Mode proxy acts as both MCP server (to Claude Code) and MCP client (to real servers):

```
Claude Code
    └── MCP client → proxy (exposes: mcp__codebox__execute_code)
                          ├── MCP client → real server A
                          ├── MCP client → real server B
                          └── sandbox executes generated code
                                  ├── proxy.serverA.tool(...)
                                  └── proxy.serverB.tool(...)
                                          ↓
                                  results merged in-process
                                          ↓
                              one result back to Claude
```

Credentials stay in the proxy, injected at dispatch time. Generated code never sees them.

---

## The Sandbox

### Cloudflare's Version
V8 isolates — separate heap, millisecond startup, disposable per snippet, capability-based access via bindings (no `fetch`/`connect` in scope).

### Node.js Equivalent: `worker_threads`

`worker_threads` are genuine V8 isolates with separate heaps. `vm` module is not sufficient (same heap, prototype escape attacks possible).

```javascript
// host
const { port1, port2 } = new MessageChannel();
const worker = new Worker(generatedCode, {
  eval: true,
  workerData: { port: port2 },
  transferList: [port2]
});

// worker (generated code only has access to port)
function callTool(server, tool, args) {
  return new Promise(resolve => {
    port.once('message', resolve);
    port.postMessage({ server, tool, args });
  });
}
```

Host receives messages, dispatches to real MCP servers with credentials, returns results. Worker never touches the network or sees a credential.

**What you get:** real memory isolation, real capability-based access, credential hiding. Startup overhead (~10–50ms) is irrelevant at Claude Code invocation rates vs LLM inference time.

---

## Restricting Tools at Invocation Time

Rather than editing `settings.json`, register the MCP server once via CLI and pass `--allowedTools` per invocation. This keeps settings files clean and makes the constraint explicit in the runner script:

```bash
# One-time registration (adds to ~/.claude/settings.json automatically)
claude mcp add codebox node ./exec-server.js

# Per-invocation: only mcp__codebox__execute_code is available
claude --allowedTools "mcp__codebox__execute_code" -p "run this script"
```

`--allowedTools` is a whitelist — unlisted tools are not offered to the model at all, equivalent to `permissions.deny` on everything else. Because it's a CLI flag rather than a file edit, the same `settings.json` works for both normal and constrained runs; the runner script controls the constraint.

**Caveat:** Full disabling of built-in tools is an open GitHub issue — `deny` / `--allowedTools` blocks calls and removes context, but behavior may vary by tool. Keeping the constraint in the runner script (rather than committed settings) means other agents using the same project settings retain normal tool access.

---

## Minimal Implementation

You don't need the full proxy/isolate stack to get most of the benefit. A ~50-line MCP server exposing one tool captures 80% of the win:

```javascript
execute_code: {
  description: "Execute a Python or bash script and return all output. Use this instead of sequential bash calls.",
  input: { code: string, language: "python" | "bash" }
}
// internally: child_process.exec with timeout
```

Add the proxy pattern and worker_thread sandbox when you need credential hiding or stronger isolation.

