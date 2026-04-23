# onlycodes Roadmap

## Goal

Validate the "Code Mode" hypothesis: deny all Claude Code built-in tools and replace them with a
single `execute_code` MCP tool. Claude writes one script per task instead of issuing N sequential
tool calls. Measure whether this reduces round-trips and improves output quality.

> **Design review complete.** See [DISCUSSION.md](DISCUSSION.md) for full findings.
> The roadmap below reflects post-review revisions.

---

## Pre-M1 — Hypothesis Validation Gate ✅ COMPLETE

**Do this before writing any code. Takes one afternoon.**

Simulated Code Mode using `claude -p --tools Bash,Write` against two fixtures: a synthetic myapp
codebase and the real psf/requests library. 5 tasks, two arms each (baseline all-tools vs.
constrained). Full methodology in `run_prevalidation.sh` and `run_prevalidation_requests.sh`.

### Methodology

- Both arms: identical `--system-prompt "You are a helpful assistant."` (eliminates CLAUDE.md
  injection as a confound), `--dangerously-skip-permissions` (no approval gates), `--no-session-persistence`
- Constrained arm: `--tools Bash,Write` only, CONSTRAINT prefix asking for one script per task
- Scored against pre-computed oracle files in `oracle/` and `oracle_requests/`
- Metrics captured per run: `total_cost_usd`, `num_turns`, `permission_denials` from stream-json

### Results

**Read/search tasks (T1–T4): hypothesis validated.**

| Task | Correctness | Cost delta | Turns |
|------|-------------|------------|-------|
| T1: Find os imports | Both ✅ | Constrained −8% | 2/2 |
| T2: Find missing env vars | Both ✅ | Constrained −24% | 2/2 |
| T3: Run pytest, summarize | Both ✅ | Constrained −19 to −26% | 2/2 |
| T4: Find variable references | Both ✅ (constrained filtered .pyc on requests) | Constrained −18 to −21% | 2/2 |

Constrained arm is consistently 8–26% cheaper on read/search/exec tasks with identical correctness
and identical turn count. Savings come from smaller tool-definition context in the API request, not
system prompt size (both arms use the same prompt).

**Write/modify tasks (T5): baseline wins.**

| Variant | Turns | Cost | Notes |
|---------|-------|------|-------|
| Baseline (Read+Edit) | 3–4 | $0.037–$0.082 | Surgical, reliable |
| Constrained Bash-only | 2–6 | $0.038–$0.094 | Correct but self-corrects on complex files |
| Constrained Bash+Write (silent) | 2–5 | $0.038–$0.059 | Write tool never discovered |
| Constrained Bash+Write (nudged) | 3–9 | $0.044–$0.111 | Write used, but more expensive |

Edit tool is surgical; Bash-based file mutation is fragile on production code with complex
structure. The model does not naturally discover Write as an intermediate step — it requires
an explicit prompt hint, and even then the write-then-run pattern adds overhead rather than saving it.

### Gate verdict

**Pass.** 5/5 tasks completed correctly in both arms. Zero silent partial failures. The hypothesis
holds for read tasks; write tasks need the Edit tool or equivalent in the real MCP server.

**Resolved open questions:**

| Question | Answer |
|----------|--------|
| Does `--tools` remove built-in tools from Claude's context? | Yes — constrained arm shows lower cache reads, confirming tool definitions are excluded |
| Does the constrained arm discover Write organically? | No — requires explicit prompt nudge; even then, not more efficient |
| Which task shapes benefit most? | Read-heavy / search / execute-and-report; write tasks favor Edit |

**New open question surfaced:** The caveman repo finding — output tokens are ~6% of session cost —
suggests the round-trip saving may be secondary to the tool-definition size saving. The real
`execute_code` MCP tool description will itself consume tokens. Keep it short.

---

## Milestone 1 — Minimal Viable Server

**Output:** Claude routes all file/shell operations through `execute_code`. Zero built-in calls.

### Pre-requisite: verify `--allowedTools`

Before anything else: run `claude --allowedTools 'mcp__codebox__execute_code'`, ask Claude to
list files, and observe whether it routes through the MCP tool or prompts for a built-in tool
approval. If it prompts or falls back, the isolation mechanism is broken and M1 cannot proceed.

### Tasks

- [ ] `package.json` — `@modelcontextprotocol/sdk` dependency
- [ ] `exec-server.js` — MCP server (stdio transport), one tool:
  - `execute_code(code: string, language: "python" | "bash", timeout_seconds?: number)`
  - Async subprocess execution (`asyncio.create_subprocess_exec` equivalent in Node)
  - Streaming stdout/stderr to MCP response as incremental text blocks
  - Hard timeout with process kill on expiry
  - Stripped env: no `HOME`, no `ANTHROPIC_API_KEY`, no credential env vars
  - Isolated working directory (not user home)
  - Network isolation: `unshare -n` or equivalent (not optional — execute_code is an attack surface
    from day 1)
  - Structured output: `{stdout, stderr, exit_code}` as typed content blocks
  - **Keep tool description short** — tool definitions add to every API request's token cost
- [ ] Session logger: append to `logs/session.jsonl`
  - Fields: `timestamp, language, code, stdout, stderr, exit_code, duration_ms`
- [ ] Retry + fallback handler:
  1. Retryable error (timeout, OOM) → retry same script once
  2. Non-retryable (syntax error, missing binary) → return error + stderr to Claude, let it revise
  3. Second failure → fall back to built-in Bash for that invocation, log fallback
  4. Two fallbacks in one session → surface warning to user
- [ ] `.claude/settings.json` — `--allowedTools` equivalent, MCP server registration

**Success criteria:**
- `--allowedTools` verification passes (10-minute manual test, blocks everything else)
- Async subprocess: no MCP session hang on scripts >5 seconds
- Network isolation confirmed: script cannot `curl` external endpoints
- Session log captures all invocations with correct fields

---

## Milestone 2 — Benchmark

**Output:** Reproducible numbers answering "does it work and is it faster?"

### Tasks

- [ ] 15-task harness with golden output oracle (checked into repo)
- [ ] Two arms: baseline (normal built-in tools) vs. execute_code only
- [ ] 3 runs each arm per task (to measure variance)
- [ ] `tools/analyze.py` — reads `session.jsonl`, computes:
  - First-attempt success rate (oracle-verified, not exit-code-only)
  - Task completion rate
  - Total token cost per task (if Claude Code exposes usage metadata)
  - Wall-clock time per task
  - Fallback rate (how often execute_code gave up and used built-ins)

### Task categories

**File Operations (5):** grep patterns across files, find missing env vars, git log for specific
files, find/replace across files, parse CSV to JSON

**Analysis (5):** LOC by language, functions with >3 params, circular import detection, TODO
extraction with file:line, p95 from log file

**Write/Execute (5):** add CLI flag with test, new FastAPI endpoint with test, parse pytest output,
multi-file refactor (print → logging), npm init + build

### Oracle

| Task type | Correctness check |
|-----------|-------------------|
| Read-only (1–10) | Exact string match against pre-computed answer |
| Edit tasks | `git diff` vs. reference patch; score = correct hunks / total; threshold ≥0.90 |
| Execute-and-report | Structured output (failure count, names) vs. known ground truth |

### Decision gate (from LLM Expert, accepted by team)

| First-attempt success rate | Action |
|---------------------------|--------|
| ≥75% AND token cost ≤ baseline | Proceed — hypothesis validated |
| 60–75% | Proceed with retry+fallback mandatory; document which task types need it |
| <60% | Hypothesis false. Stop. Write up findings. |
| Any undetected silent partial failure | Block until oracle detects it reliably |

---

## Suspended

**M3 — Sandbox Isolation (worker_threads)**
Dropped. `worker_threads` shares Node.js process memory; `require('fs')` works from workers. Not a
real security boundary. Network isolation via `unshare -n` in M1 is the actual mitigation. If
stronger isolation is needed later, use a container or seccomp, not worker_threads.

**M4 — Proxy Fan-Out**
Dropped. Design has two blocking issues: (1) can't serve stdio to Claude while being an MCP client
over stdio — streams fight; (2) credentials injected at dispatch appear in session.jsonl and
Claude's context window. Revisit only post-M2 and only with HTTP+SSE on the Claude-facing side.

---

## Open Questions

| Question | Resolves at |
|----------|-------------|
| Does async subprocess within stdio MCP eliminate the blocking hang? | M1 implementation |
| What is the fallback target — built-in Bash, or fail-closed? | M1 design decision |
| Does Claude Code expose token usage metadata per session? | M2 design |
| At what success rate does the customer actually route their workflow here? | Post-M2 |
| Does Claude naturally write parallel scripts (asyncio.gather) or sequential? | M2 logs |
| How short can the execute_code tool description be without hurting task quality? | M1 tuning |
