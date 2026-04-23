# Design Review: onlycodes

**Participants:** Architect, Senior Engineer, MCP Engineer, LLM Expert, Customer
**Format:** 2-round async discussion
**Question:** Does this actually work? Are we saving any time?

---

## Round 1 Findings

### Architect

**Fundamental flaw in the hypothesis.** LLMs don't write better code than they call tools — they
write better code *when they can iterate*. Built-in tools give Claude structured feedback per
operation. A single `execute_code` call forces Claude to get everything right in one shot. You'll
trade N cheap sequential calls for fewer but much longer scripts with higher failure rates. Net
round-trips may increase.

**M3 is architecturally incoherent.** `worker_threads` shares Node.js process memory. You cannot
prevent `require('fs')` from a worker thread. Real isolation needs `seccomp`, a container, or a VM.
M3 as specced ships false security.

**Missing from the plan entirely:**
- Error recovery: when a 40-line script fails on line 31, Claude can't read partial state without
  another execute_code call
- Streaming/progress: long operations block until completion or timeout — no course-correct
- State management: built-in tools persist cwd and env across calls; execute_code resets each time
- Security in M1–M2: arbitrary code execution with no sandbox for two full milestones

**Verdict:** Move M2's benchmark before M1. Kill M3. Kill M4 (proxy is reimplementing what was
removed). Add fallback: let Claude opt back to built-ins when execute_code fails twice.

---

### Senior Engineer

**`permissions.deny` won't do what you think.** Built-in tools are hardcoded in the Claude Code
client. `deny` controls execution approval, not tool visibility. Claude still *sees* them, still
tries to call them. Need `--allowedTools` CLI flag to whitelist the MCP tool only — and that
behavior is undocumented, fragile across releases.

**M3 confirmed broken.** Workers share process memory. `require('fs')` works from a worker.

**M2 comparison measures the wrong things.** Round-trip count is gameable. "Estimated equivalent
Bash calls" is self-reported by the tool. Need:
- Task completion rate (did it produce correct output)
- Wall-clock time to correct output
- First-attempt success rate
- Total token cost

Five prompts is an anecdote, not data.

**Edge cases the plan ignores:**
- Streaming output: Bash tool streams stdout; temp-file approach blocks until done
- Binary file handling: Read can display images; execute_code returns text only
- Edit verification: built-in Edit does exact-match replacement with conflict detection; a Python
  `open().write()` silently overwrites with no undo
- CWD state: built-ins share context; execute_code resets each invocation

---

### MCP Engineer

**MCP returns structured content, not stdout.** execute_code returning raw subprocess output is
untyped blobs. The spec expects `{type: "text"|"image"|"resource"}` with schema.

**stdio transport blocks during execution.** JSON-RPC over stdio is synchronous-per-request. If
execute_code runs a 30-second subprocess, the entire MCP session blocks — no heartbeat, no
cancellation, no progress. Claude Code will surface a hang with no diagnostics. This is an M1
kill shot.

**`permissions.deny` is a policy hint.** Not an enforcement boundary. If Claude Code updates and
changes settings parsing, the baseline assumption breaks silently.

**Single `execute_code` tool is a prompt injection surface.** Any output Claude reads containing
code is executed next turn.

**M4 has a design impossibility.** A proxy can't serve stdio to Claude while also being an MCP
client over stdio — two streams fight over stdin/stdout. Downstream leg needs SSE or socket.

**M4 credential leak.** Credentials injected at dispatch will appear in session.jsonl (M2), in
Claude's context window, and potentially in any log.

---

### LLM Expert

**Hypothesis is partially sound but overstated.** Two distinct claims:
- Claim A: scripts are more *reliable* than tool calls — training data supports this
- Claim B: scripts are more *efficient* (fewer round-trips) — only true if the script succeeds
  first-try. That's the unstated load-bearing assumption the entire roadmap rests on.

**Claude will hallucinate in specific patterns.** File paths (assumes CWD), binary existence,
environment variable names. The worst case: bash scripts that look correct and produce partial
side effects before failing — no rollback, no clean error.

**M1's smoke test (`ls`) proves nothing.** Trivially easy. It validates the MCP plumbing, not
the hypothesis.

**Silent partial failure is the real worst case.** Script exits 0, produces wrong output, no retry
triggered. Scores "success" in M2's metrics. Never caught.

**Retry token math.** One-shot fails and regenerates: ~2,400 tokens. Sequential tool calls for
same task: ~1,700 tokens. One-shot only wins if first-attempt success rate exceeds ~70%. Below
that, sequential is cheaper per task. This is the load-bearing number M2 must measure.

---

### Customer

**What was I promised vs. what the roadmap delivers.** Promised: faster, more reliable tool calls.
Roadmap delivers: a prototype and some observability. No controlled comparison before M2, and M2's
"estimated equivalent Bash calls" metric is self-reported by the tool.

**What the roadmap doesn't tell me.** What happens when a script is wrong? Does Claude retry? Does
the session die? What does a 30s timeout look like to the user — useful error or hung terminal?

**When will I know if it works?** M2 gives numbers but no control group methodology. I might not
know until I'm already depending on it.

**Biggest risk.** M3 and M4 are architectural pivots that may invalidate M2's baseline. I'm
waiting through two rewrites before the thing stabilizes.

**The one question nobody answered.** When Claude's generated script fails, what exactly happens
next — and who measured it?

---

## Round 2 Convergence

### What the team agreed on

**1. Validate the hypothesis before writing a single line of M1 code.**

Run 5 tasks manually — no infrastructure. One afternoon. Give Claude a task with only the existing
Bash tool but constrain it to "one script per turn." Compare against the same tasks with normal
tool access. If constrained mode fails 3+ tasks or produces silent wrong output on any, stop.
(Architect updated after MCP Eng's stdio-blocking finding made M1-first impractical anyway.)

**2. The stdio blocking issue is real but solvable within M1.**

MCP Engineer's fix: use `asyncio.create_subprocess_exec` for the child process inside the MCP
server. Stream stdout/stderr incrementally. Enforce hard timeout via `asyncio.wait_for`. On
`CancelledError` from the MCP runtime, `process.kill()`. ~40 lines. The MCP server itself stays
on stdio; only the subprocess execution is async. Senior Engineer proposed SSE transport instead —
valid but more complex. SSE is the right choice if M4 is ever revived.

**3. `permissions.deny` is unverified. Test it first.**

Nobody on the team has run it against a live Claude Code session. `--allowedTools` CLI flag is the
correct mechanism (`--allowedTools 'mcp__codebox__execute_code'`). Run one 10-minute test: ask
Claude to perform a task that would use a built-in tool, observe whether Claude Code routes to the
MCP tool or prompts for approval. If it prompts or falls back, the entire baseline is invalid.

**4. Kill M3 (worker_threads). Kill M4 (proxy fan-out).**

Unanimous. M3 ships false security. M4 has an unresolved transport conflict and a credential leak
into session.jsonl. Both milestones are out. Revisit M4 only post-benchmark, only with HTTP+SSE
on the Claude-facing side.

**5. Network isolation is required in M1, not M3.**

MCP Engineer: execute_code can `curl` attacker-controlled endpoints, exfiltrate env vars, write
to `~/.claude/`. Mitigation: `unshare -n` (Linux network namespace) or at minimum stripped env
(no HOME, no ANTHROPIC_API_KEY). This is not optional; the risk is present in M1 day 1.

**6. Retry and fallback behavior is specified.**

execute_code fails →
1. If retryable error (timeout, OOM): retry once with same script
2. If non-retryable (syntax error, missing binary): return error + stderr to Claude, let it revise
3. If second failure: fall back to built-in Bash for that specific invocation, log the fallback
4. Two fallbacks in one session: surface a warning to user

**7. M2 metrics are replaced entirely.**

| Old (wrong) | New (correct) |
|-------------|---------------|
| Round-trip count | First-attempt success rate |
| Estimated equivalent Bash calls | Total token cost per task |
| Error rate (exit code) | Task completion rate (oracle-verified) |
| Avg lines of code per script | Wall-clock time per task |

**8. Decision thresholds before proceeding to production.**

From LLM Expert, accepted by team:
- First-attempt success ≥75% AND token cost ≤ baseline sequential: proceed with M1
- First-attempt success 60–75%: proceed with mandatory retry+fallback baked in
- First-attempt success <60%: hypothesis false, stop
- Any undetected silent partial failure: block until oracle catches it reliably

---

### Benchmark Design (15 tasks, 3 categories)

From Senior Engineer and LLM Expert, merged:

**File Operations (5)**
1. Find all Python files that import `os.path`
2. Find all env vars referenced in `tts_server/` that are never set in `.env`
3. List all git commits touching a specific file in the last 30 days
4. Find/replace a string across multiple files
5. Parse a CSV and output JSON

**Analysis (5)**
6. Count lines of code by language in a repo
7. Find all functions with >3 parameters
8. Check for circular imports in a package
9. List all TODOs with their file:line
10. What's the p95 from the last benchmark log?

**Write/Execute (5)**
11. Add a `--dry-run` flag to an existing CLI
12. Create a new FastAPI endpoint with a test
13. Run pytest and summarize failures
14. Refactor: replace all `print` with `logging.debug` across a package
15. Init an npm project, install deps, run build

**Oracle:**
- Read-only tasks (1–10): exact string match against pre-computed answer
- Edit tasks (11, 12, 14): `git diff` against reference patch; score = correct hunks / total hunks;
  threshold ≥0.90
- Execute-and-report (13, 15): extract structured output (failure count, names), compare against
  known ground truth

Run each task 3× per arm (baseline tools vs. execute_code only) to measure variance.

---

### Revised Roadmap

**Pre-M1: Hypothesis validation (1 day, no code)**
- Constrain Claude to "one Bash script per turn" manually
- Run 5 representative tasks
- Pass/fail gate: ≥4/5 tasks complete correctly, zero silent failures
- If gate fails: stop. Document why.

**M1: Minimal server (2–3 days)**
- `exec-server.js` with async subprocess, streaming output, hard timeout
- Stripped env, isolated cwd, `unshare -n` for network isolation
- `--allowedTools` verification test before anything else
- Session logger: `{timestamp, language, code, stdout, stderr, exit_code, duration_ms}`
- Retry+fallback handler

**M2: Benchmark (2–3 days)**
- 15-task harness with golden output oracle
- Two arms: baseline vs. execute_code
- 3 runs each for variance
- Output: comparison table of first-attempt success rate, token cost, wall-clock time

**Decision gate after M2:**
- Numbers meet threshold → write up findings, consider production path
- Numbers don't → document which task categories failed and why, stop

**M3, M4: Suspended** pending M2 results.

---

## Open Questions (still unresolved)

| Question | Who needs to answer | When |
|----------|---------------------|------|
| Does `--allowedTools` suppress built-ins from Claude's context, or just block execution? | Anyone with a live session | Before M1 |
| Does async subprocess within stdio MCP fully eliminate the blocking hang? | MCP Eng | M1 implementation |
| What is the fallback target? Built-in Bash, or fail-closed? | Architect + Senior Eng | M1 design |
| Does Claude Code expose enough token usage metadata to measure cost per task? | Senior Eng | M2 design |
| At what first-attempt success rate does the Customer actually route their workflow here? | Customer | Post-M2 |

---

## Customer's Verdict

> "Run the 20-task oracle first. If first-attempt success rate on real tasks isn't meaningfully
> better than baseline tool calls, M1–M4 is solving the wrong problem. I'd rather know that now.
> A comparison table — same tasks, tool-call path vs. script path, wall-clock time, first-attempt
> success rate, token cost — is the one deliverable that would make me believe it. Published
> numbers I can reproduce. Not a curated demo."
>
> "If the answer is 'works reliably for file transforms, unreliable for multi-step API sequences'
> — that's actually useful. I can route accordingly."
