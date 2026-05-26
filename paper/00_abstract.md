# 00 — Abstract

**Status:** placeholder. Do not finalize until §5 numbers freeze.

Target length: ~180 words.

## Skeleton

1. **One-sentence framing.** Modern coding agents expose multiple tool surfaces — IDE primitives (Read/Grep/Glob/Edit/Write), bash, and MCP `execute_code` — but the field has three contradictory claims about which one matters: SWE-agent (NeurIPS 2024) argues for specialized IDE tools; mini-SWE-agent (2025) shows bash alone suffices; Anthropic and Cloudflare's "Code Mode" claim 98–99% token reductions by routing through `execute_code` MCP.
2. **One-sentence method.** We run an integrity-clean three-arm ablation (`tool_rich` / `bash_only` / `code_only`) on (a) 93 synthetic computation tasks with hidden deterministic graders and (b) 100 SWE-bench Mini modification tasks under the standard post-agent `test_patch` protocol — same model, same harness, same prompts.
3. **One-sentence comparison classes.** Direct contrast: SWE-agent's ACI-vs-shell two-arm result, mini-SWE-agent's bash-only result, the Anthropic/Cloudflare external-MCP token claims.
4. **One-sentence headline.** Cost asymmetry flips sign between regimes: `code_only` is \result{...}{...} cheaper on computation tasks; `tool_rich` is \result{...}{...} cheaper on modification tasks; pass rates are statistically tied within each regime.
5. **One-sentence interpretation.** The sign-flip is predicted by the Capability Overlap Principle (Zhang et al. 2026) and supports a *regime-dependent* optimal tool surface — not the universal "less is more" or "ACI wins" framings.

## Working draft (do not freeze)

> Modern coding agents expose multiple tool surfaces — IDE primitives, bash, and MCP code-execution — and the field has three contradictory claims about which one matters: SWE-agent argues for specialized IDE tools, mini-SWE-agent shows bash alone suffices, and recent industry work claims large token reductions from a single `execute_code` MCP tool. We run the missing crossed comparison: an integrity-clean three-arm ablation (`tool_rich` / `bash_only` / `code_only`) on 93 synthetic computation tasks and 100 SWE-bench Mini modification tasks, holding model, harness, and prompts fixed. We find that cost asymmetry flips sign between regimes: `code_only` is ~33% cheaper than `tool_rich` on computation tasks, but `tool_rich` is ~11% cheaper than `code_only` on modification tasks — with pass rates statistically tied within each regime. The sign-flip is consistent with the Capability Overlap Principle and challenges both the "specialized tools always win" and "less is more" framings. Optimal tool surface is regime-dependent, not universal.

(~155 words. Numbers placeholder; finalize via `\result{}` macros once seed variance is in.)
