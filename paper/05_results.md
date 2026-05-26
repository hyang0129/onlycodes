# 05 — Main Results

**Target length:** 2.0 pages (ceiling 2.25). The single largest section.

**Status:** outline only. Tables and figures **blocked** until the post-#287 seed runs finish + auth-recovery completes. Do not write prose for §5.1–5.5 before numbers freeze.

---

## 5.1 Headline table (Table 2)

Per-arm aggregates split by regime. Form:

| Regime | Arm | Pass rate (± CI) | Total cost (USD) | Median cost/inst | Turns | $/turn |
|---|---|---|---|---|---|---|
| Computation (artifact, n=93) | tool_rich | \result{...} | \result{...} | \result{...} | \result{...} | \result{...} |
| Computation (artifact, n=93) | bash_only | \result{...} | \result{...} | \result{...} | \result{...} | \result{...} |
| Computation (artifact, n=93) | code_only | \result{...} | \result{...} | \result{...} | \result{...} | \result{...} |
| Modification (SWE-bench, n=100) | tool_rich | \result{...} | \result{...} | \result{...} | \result{...} | \result{...} |
| Modification (SWE-bench, n=100) | bash_only | \result{...} | \result{...} | \result{...} | \result{...} | \result{...} |
| Modification (SWE-bench, n=100) | code_only | \result{...} | \result{...} | \result{...} | \result{...} | \result{...} |

**Lead with the sign-flip:** "On the computation regime, `code_only` is \resdelta{}-cheaper than `tool_rich`; on the modification regime, `tool_rich` is \resdelta{}-cheaper than `code_only`. Pass rates within each regime are statistically indistinguishable."

## 5.2 Sign-flip figure (Figure 1)

See `figures_outline.md` Figure 1. Two-bar chart per regime, `code_only / tool_rich` cost ratio. Artifact: ratio < 1.0 (code_only cheaper). SWE-bench: ratio > 1.0 (tool_rich cheaper). Error bars from seed variance.

**Caption draft:** *"Cost ratio `code_only / tool_rich` by regime. Bars below 1.0 mean `code_only` is cheaper than the full IDE tool surface; bars above 1.0 mean `tool_rich` is cheaper. The sign-flip across regimes is consistent with the Capability Overlap Principle (Zhang et al., 2026): IDE primitives are pure overhead on computation tasks where bash already suffices, but earn their token budget on modification tasks via exploration efficiency. Pass rates within each regime are statistically tied (see Figure 2)."*

## 5.3 Capability invariance (Figure 2)

Per-arm pass rate × regime, with 95% CI bars from seed variance. Expected spread: ≤2pp within each regime.

**Caption draft:** *"Pass rates by arm and regime. Within each regime, all three arms are statistically indistinguishable. The cost asymmetry in Figure 1 lives entirely in cost and turn count, not in capability — supporting a tool-tax view where the tax is real but task-conditional."*

## 5.4 Per-repo breakdown (Table 3)

For SWE-bench Mini, split per-repo (Django / Sphinx / sklearn / matplotlib / xarray / sympy / seaborn / astropy). Two questions to answer:

1. Does the modification-regime sign-flip hold across repos?
2. Are there repo-specific reversions (e.g., Sphinx is exploration-heavy, sklearn is dependency-fragile)?

Per the seed_1 audit (issue #158, 2026-05-25), Django and Sphinx are largely tool_rich-favored; matplotlib is flat; xarray and astropy may discriminate differently. Confirm post-variance.

## 5.5 Agreement matrix

3-arm PASS/FAIL agreement per instance:

| tool_rich | bash_only | code_only | count |
|---|---|---|---|
| PASS | PASS | PASS | ... (unanimous PASS) |
| FAIL | FAIL | FAIL | ... (unanimous FAIL) |
| various splits | ... | ... | ... |

Defends: "the regime-level cost asymmetry is not driven by a small number of discriminating instances; even on unanimous-PASS instances, cost differs systematically by regime."

## 5.6 Generalization to Codex CLI (~0.3 page)

One paragraph + a small inset table. Form:

| Regime | Arm | Claude Code | Codex CLI |
|---|---|---|---|
| Modification (SWE-bench) | tool_rich cost | $X | $Y |
| Modification (SWE-bench) | code_only cost | $X' | $Y' |
| Modification (SWE-bench) | code_only / tool_rich | >1.0 | <1.0 |

**Key claim:** Codex's bash-first prompt design inverts the SWE-bench ranking — `code_only` is cheaper than `tool_rich` on Codex even though `tool_rich` is cheaper on Claude. **Therefore optimal tool surface is jointly determined by regime AND agent design**, not by a universal "less is more" or "ACI wins" prescription.

**Caveat for the paragraph:** "We do not claim Codex's behavior generalizes to other GPT-family agents — n=1 surface. The point is that a single counterexample is sufficient to reject the universal-optimum framings of prior work."

---

## Drafting order

1. **Wait for**: auth-recovery rerun (12 sympy+mwaskom × 3 arms, in flight per [issue #158 comment 2026-05-25](https://github.com/hyang0129/onlycodes/issues/158)).
2. **Wait for**: seeds 2/3 to finish on Claude SWE-bench (in progress).
3. **Then**: generate paper/data/*.csv from the run-dir summary CSVs.
4. **Then**: figures_src/01_signflip.py, 02_capability_invariance.py, 03_cost_decomposition.py.
5. **Then**: prose for §5.1, §5.4, §5.5 (mechanical from numbers).
6. **Then**: §5.6 (Codex generalization, depends on Codex seed_1 being complete — it is).
7. **Then**: §5.2 and §5.3 captions.
8. **Then**: cross-check every numerical claim in §5 prose maps to a `\result{}`/`\resdelta{}` macro.
