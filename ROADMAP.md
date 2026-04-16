# onlycodes Roadmap

## Goal

Validate the "Code Mode" hypothesis: deny all Claude Code built-in tools and replace them with a
single `execute_code` MCP tool. Claude writes one script per task instead of issuing N sequential
tool calls. Measure whether this reduces round-trips and improves output quality.

> **Design review complete.** See [DISCUSSION.md](DISCUSSION.md) for full findings.
> The roadmap below reflects post-review revisions.

---

## Pre-M1 — Hypothesis Validation Gate

**Do this before writing any code. Takes one afternoon.**

Manually constrain Claude to "one Bash script per turn" using the existing Bash tool. No MCP
server, no settings changes. Run 5 representative tasks side-by-side (normal tools vs. one-script
constraint). Record: did it complete, was the output correct, how many rounds, what happened on
failure.

**Pass gate:** ≥4/5 tasks complete correctly, zero silent partial failures (exit 0, wrong output).

**If gate fails:** stop. Document which task types broke and why. Do not proceed to M1.

**Tasks to run:**
1. Find all Python files that import a specific module
2. Find env vars referenced in a codebase but never set in `.env`
3. Add a `--dry-run` flag to an existing CLI
4. Run a test suite and summarize failures
5. Find/replace a string across multiple files and verify the result

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
| Does `--allowedTools` remove built-ins from Claude's context, or just block execution? | Pre-M1 test |
| Does async subprocess within stdio MCP eliminate the blocking hang? | M1 implementation |
| What is the fallback target — built-in Bash, or fail-closed? | M1 design decision |
| Does Claude Code expose token usage metadata per session? | M2 design |
| At what success rate does the customer actually route their workflow here? | Post-M2 |
| Does Claude naturally write parallel scripts (asyncio.gather) or sequential? | M2 logs |
| Which task shapes benefit most — read-heavy vs. multi-step write? | M2 analysis |
