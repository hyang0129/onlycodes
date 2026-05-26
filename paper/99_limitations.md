# 99 — Limitations

**Status:** required by KDD workshop submission (desk-reject if missing); placeholder ready to be expanded with concrete instance-level details after numbers freeze.

**Target length:** 0.25 page (ceiling 0.5). Five bullets.

---

## Working list (will be reduced to 4–5 for the paper)

### Agent surface coverage

We evaluate two agent surfaces: Claude Code (claude-sonnet-4-6, version 2.1.139) and Codex CLI (gpt-5.5). The agent-design dependence claim in §5.6 rests on these two surfaces only. We do not run Cursor, Aider, or open-source surfaces (SWE-agent, OpenHands, Cline). Whether the sign-flip generalizes to surfaces we did not test is open.

### Benchmark scope

- **Computation regime is synthetic.** The 93 artifact tasks have hidden deterministic graders by construction. The result generalizes to other deterministic-grader computation benchmarks (LeetCode-style, scientific Python notebook tasks) but **not** to graders that require human judgement or LLM-as-judge scoring.
- **Modification regime is SWE-bench Mini.** 100 instances sampled from SWE-bench Verified; we do not run the full 500-instance Verified or the 2,294-instance Lite. Per-repo cost asymmetries reported in §5.4 are noisier than the headline regime-level asymmetry. Larger SWE-bench cuts may shift per-repo magnitudes.
- **Repo selection bias.** SWE-bench Mini under-samples large Python projects (Django/Sphinx skew) and over-samples scientific Python (matplotlib/sklearn/xarray/sympy/seaborn/astropy). General industrial-codebase shapes (Java/Go/TypeScript, build systems, microservice repos) are not tested.

### Protocol scope

- **Post-#287 protocol only.** We restore standard SWE-bench `test_patch`-post-agent semantics; all numbers in this paper are post-fix. Pre-#287 data (archived in `runs/swebench/_legacy_pre_287/`) is not comparable.
- **Single Claude model version.** claude-sonnet-4-6 v2.1.139. We do not test claude-opus, claude-haiku, or earlier Sonnet versions. Whether the sign-flip holds across model scales is open.

### Statistical power

- Three seeds per (instance, arm). The headline sign-flip (22pp gap between cost-ratio deltas) is well above seed variance (typically 1–3pp); per-repo SWE-bench breakdowns have lower power and should be read as suggestive.
- 12 SWE-bench instances (sympy + mwaskom) initially failed due to credential rotation in seed_1 and were re-run; documented in appendix.

### Cost measurement

- Claude cost is reported via the agent's per-message API usage telemetry — accurate to within the rounding precision of the telemetry stream.
- Codex cost is estimated from token usage × model price per [Issue #253](https://github.com/hyang0129/onlycodes/issues/253) — slightly less precise than Claude's direct telemetry.
- Wall-clock time is reported in the appendix but not used in the headline; we focus on dollar cost and turn count.

### What we deliberately did not test

- **Multi-shot prompting / scratchpad reuse.** All arms run once per (instance, arm); no self-correction loops, no human-in-the-loop, no test-driven iteration beyond what the agent does autonomously.
- **External MCP tools.** The `code_only` arm exposes a single `execute_code` MCP. We do not benchmark against `external` MCP tool surfaces (Slack, GitHub, Drive — the surfaces Anthropic and Cloudflare report on). Our claim is internal-to-the-coding-task; external MCP is a different question.

---

## Final shape for the paper (target: 5 bullets, ~0.25 page)

1. Two agent surfaces (Claude Code, Codex CLI); third-surface generalization is open.
2. Modification benchmark is SWE-bench Mini (100 inst), not full Verified — per-repo asymmetries noisier than the regime-level headline.
3. Post-#287 protocol only; legacy pre-#287 data archived and not reported.
4. Three seeds; statistical power high for headline sign-flip, lower for per-repo breakdowns.
5. We do not test multi-shot prompting or external MCP tool surfaces.
