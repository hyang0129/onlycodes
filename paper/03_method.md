# 03 — Method

**Target length:** 1.75 pages (ceiling 2.0). **§3.3 is non-negotiable** — keep ≥0.5 page even if other subsections shrink.

## Structure (4 subsections)

### 3.1 Three-arm tool surface (~0.5 page)

Define each arm by what tools are allowed/disallowed at the agent-process level. The harness sets these via `--allowedTools` / `--disallowedTools` for Claude Code and equivalent CLI flags for Codex.

| Arm | Allowed tools | Implementation reference |
|---|---|---|
| `tool_rich` | Full Claude Code surface: `Read`, `Grep`, `Glob`, `Edit`, `Write`, `Bash`, plus default agents/skills | `runner.py:ClaudeRunner.build_tools_flags` (no `--disallowedTools` set) |
| `bash_only` | `Bash` only; all IDE primitives explicitly disallowed | `--disallowedTools Read,Edit,Write,Grep,Glob,...` |
| `code_only` | Single MCP tool `mcp__codebox__execute_code` (Python + Bash inside a persistent REPL kernel) | `--allowedTools mcp__codebox__execute_code,mcp__codebox__list_tools` + all built-ins disallowed |

The `code_only` arm uses the `exec_server/` MCP stack: Node-based exec-server (`exec-server.js`) bridges to a Python kernel helper (`codebox.py`, `python_kernel.py`) that maintains state across `execute_code` invocations. The persistent kernel is the key design choice — without it, every code execution starts a fresh interpreter and the round-trip savings of "one script per task" collapse.

**Disclosure:** The bash_only arm is a direct port of the mini-SWE-agent scaffold to our harness. We do not re-implement; we use `--disallowedTools` to constrain the same Claude Code binary the other two arms use.

### 3.2 Harness design (~0.4 page)

Per-instance setup:
- **Repo clone + venv setup.** Clone the instance's repo at `base_commit`, set up a Python venv outside the OverlayFS overlay, install editable dependencies. OverlayFS provides per-arm filesystem isolation; venv lives outside so `.egg-info` survives `git clean`.
- **Git history strip.** `strip_git_history()` collapses the repo to a single orphan commit, deletes all refs/packed-refs/reflogs, runs `git gc --prune=now`. The agent cannot recover the reference fix via `git log`. Uses fixed author date so re-stripping produces the same orphan SHA (idempotent).
- **Overlay refresh between arms.** Rather than `git reset` (which can't un-create files added during a previous arm), we unmount → delete upper+work dirs → recreate → remount → re-strip history. Cache lockfile drift (agent leaked a pip install) triggers full cache entry rebuild.

Per-arm setup:
- **Subprocess isolation.** `run_claude()` creates a temp `CLAUDE_CONFIG_DIR` containing only `.credentials.json` + `.claude.json`. The agent never sees the parent environment's `CLAUDE_CONFIG_DIR`, `ANTHROPIC_API_KEY`, or session-persistence state. Each invocation passes `--dangerously-skip-permissions --no-session-persistence`.
- **Wall-time cap.** Per-arm wall budget (default 3600 seconds) is enforced via `subprocess.run(timeout=...)`. Timed-out runs are marked FAIL with a recorded reason.

### 3.3 Evaluation integrity (~0.4 page) — **the post-Issue-#287 protocol**

The lead-with claim of this subsection: *we ran into and fixed a real integrity bug in our own harness, and the numbers in this paper are post-fix.*

**The bug.** Our original harness (April 2026) applied SWE-bench's `test_patch` *before* the agent ran. This placed the hidden test files on disk during the agent's execution window. While [Issue #226](https://github.com/hyang0129/onlycodes/issues/226) (May 2026) closed the `git diff` vector by committing the patch to HEAD, the test files themselves remained directly readable via `cat tests/test_added.py` or `grep -r`. An agent that read the test file could lift the exact assertions and pass without solving the underlying problem.

**The fix.** [Issue #287](https://github.com/hyang0129/onlycodes/issues/287) (May 23, 2026) defers `apply_test_patch` and the pre-flight `pytest --collect-only` check to *after* the agent runs, restoring the standard SWE-bench evaluation protocol. The result: agent-modified test files are nullified by force-revert + post-agent application; the agent never sees the assertions it must reconstruct.

**Empirical validation.** A 100-instance × 2-surface audit ([issue #158 comment 2026-05-23](https://github.com/hyang0129/onlycodes/issues/158)) cross-checked every test-modification cheat attempted by either agent against the gold patch's blast radius — **0 of 13 cases propagated to the grader** under the post-#287 protocol. The agent-behavior signal (Codex modifies test files in 63/100 runs, Claude in ~9/100) is preserved as a behavioral observation, but PASS/FAIL outcomes reflect actual implementation fixes, not cheating.

**Scope of numbers.** All SWE-bench numbers in this paper are post-#287. Pre-#287 runs have been archived to `runs/swebench/_legacy_pre_287/` and are not comparable.

### 3.4 The Capability Overlap framing (~0.3 page)

Zhang et al. (*Are Tools All We Need? Unveiling the Tool-Use Tax in LLM Agents*, arXiv:2605.00136, Apr 2026) formalize the tool-use tax inequality: a tool provides net benefit iff its task-specific capability gain exceeds the per-call cost of carrying the tool's definition in context. The principle is general (math, QA, multi-hop reasoning) and we extend it to coding-agent IDE primitives.

Under Capability Overlap, the redundancy table (§6) reads as follows: five of six Claude Code IDE primitives are bash-subsets in *capability* (Read, Grep, Glob, Write are syntactic sugar over `cat`/`grep`/`find`/`heredoc`; `Edit` has unique non-overlapping capability via atomic byte-precise replace with lint). The per-call tax (~$0.005/turn for the IDE tool definitions in Claude Code's system message) is task-invariant; the *capability gain* depends on the task regime. On computation tasks, gain ≈ 0 (no codebase structure to exploit) → tax dominates → `code_only` wins. On modification + multi-file tasks, IDE tools' exploration efficiency saves enough turns that the tax is offset → `tool_rich` wins.

The sign-flip in §5 is the empirical signature of this inequality crossing zero between regimes.

---

## Drafting notes

- §3.3 is the most consequential subsection for review. **Lead with our own bug.** Reviewers who see voluntary disclosure of an integrity issue from a self-driven audit treat the rest of the paper more charitably. Sandbag it and a sharp reviewer-2 will smell it.
- §3.4 is short. The full theoretical argument lives in the Zhang et al. citation; we use it as a framing, not re-derive.
- **Do not commit to** a particular dollar value for the per-turn IDE tax in the abstract or §1 — that number depends on which IDE primitive ablation we do and which tokenizer accounting we use. Specify in §5.
