# Figure Candidates — KDD 2026 Workshop Submission

Working list of figure candidates. Not a commitment — the final cut depends on which numbers freeze cleanly in days 3–4.

Sources: [outline.md](outline.md) §5–§7; issue [#158](https://github.com/hyang0129/onlycodes/issues/158).

---

## Recommended cut (3 figures + Table 1)

These map one-to-one onto the three contribution bullets in [outline.md](outline.md) §1.

### Figure 1 — Sign-flip headline
- **Section:** §5.2 (Main Results).
- **Content:** Two-bar chart per regime. Y-axis: cost ratio `code_only / tool_rich`. Artifact bar `<1.0` (code_only cheaper); SWE-bench bar `>1.0` (tool_rich cheaper). Error bars from seed variance. One panel per agent surface (Claude Code primary, Codex CLI secondary).
- **Why:** Defends contribution bullet #1 — the regime-dependent sign-flip. **The single figure that justifies the paper.**
- **Source assets:** Numbers from [seed_1 summary CSVs](#numbers-data). Plot script: `figures_src/01_signflip.py`. Sidecar: `fig.01_signflip.numbers.csv`.

### Figure 2 — Capability invariance
- **Section:** §5.3 (Main Results).
- **Content:** 3×2 grid of pass-rate bars (3 arms × 2 regimes). Y-axis: pass rate with 95% CI. Shows ≤2pp spread within each regime — capability is regime-invariant across arms.
- **Why:** Defends contribution bullet #2. Visualizes that the sign-flip is in cost, not in capability — critical for the "tool-use tax exists but is regime-conditional" framing.
- **Source assets:** Same CSV as Figure 1. Plot script: `figures_src/02_capability_invariance.py`.

### Figure 3 — Per-regime cost decomposition
- **Section:** §5.1 / §5.4.
- **Content:** Stacked-bar or grouped-bar showing total cost decomposed by (cost-per-turn × turn-count) for each arm × regime. Highlights that `tool_rich`'s per-turn cost is always higher (~$0.024 vs ~$0.019) but its turn count is lower on the modification regime.
- **Why:** Defends the mechanism in §7 — *the per-turn tax is real but is more-than-offset by exploration efficiency in the right regime.*
- **Source assets:** Plot script: `figures_src/03_cost_decomposition.py`.

### Table 1 — IDE primitive ↔ bash redundancy
- **Section:** §6 (its own short section). Static — does not require numbers freeze.
- **Content:** 6-row table (Read / Grep / Glob / Edit / Write / Bash) × 3 columns (primitive / bash equivalent / "capability beyond bash?").
- **Why:** Pedagogical anchor. Establishes that five of six tools are bash subsets, isolating `Edit` as the one non-redundant primitive — and the sign-flip says even the redundant tools earn their keep on modification tasks via exploration efficiency.

---

## On the bubble (would be Figure 4 if budget allowed)

### Agreement matrix per regime
- **Section:** §5.5.
- **Content:** Sankey or matrix showing PASS/FAIL agreement across arms per instance. Most instances unanimous; signal lives in 6-ish split instances per repo.
- **Why considered:** Calibrates Reviewer 2 on noise — *"we're not chasing 6 instances out of 50."*
- **Why not in top 3:** Could ride as a table in §5.5 prose. Promote to a figure only if the discriminating-instance analysis becomes a contribution by itself.
- **Swap criterion:** If §5.4 per-repo breakdown comes in flat, promote agreement matrix in place of Figure 3.

### Agent-surface comparison
- **Section:** §5.6 (Codex generalization).
- **Content:** Two panels — Claude vs Codex — showing `code_only / tool_rich` cost ratio on SWE-bench. Codex's ratio is <1.0 (code_only cheaper), Claude's is >1.0 (tool_rich cheaper).
- **Why considered:** Defends contribution bullet #3 (agent-design dependence) with one image.
- **Why not in top 3:** Could combine with Figure 1 as a second panel. Probably better as panel-of-Figure-1 than standalone.

---

## Cut (table-only or appendix)

### Per-instance cost scatter
- Same data as Figure 3 — redundant. Push to appendix.

### Token-overhead decomposition (system prompt vs tool defs vs results vs reasoning)
- From issue #158 stretch list. Interesting but not load-bearing for the sign-flip story. Appendix.

### Pass-rate histograms
- Capability invariance is better shown as bars (Figure 2). Histograms add nothing.

---

## Production order

1. **Table 1 (redundancy table)** — static markdown → LaTeX, no data dependency. Write today.
2. **Figure 2 (capability invariance)** — pass rates already stable from seed_1; can produce immediately.
3. **Figure 1 (sign-flip headline)** — depends on seed_1 + post-recovery aggregates. Block on auth-failed sympy/mwaskom rerun.
4. **Figure 3 (cost decomposition)** — same data dependency as Figure 1; produce alongside.

---

## Open questions

1. **One panel per agent surface or fold Codex into Figure 1?** Codex as a second panel of Figure 1 keeps the agent-surface story visible without spending a figure slot.
2. **Y-axis units for Figure 1: ratio, percent delta, or absolute dollars?** Ratio is regime-comparable; percent delta is intuitive; dollars are reviewer-grippable. Default to ratio with absolute dollars in caption text.
3. **Color encoding for the three arms.** Need a 3-class palette readable in B&W (workshop print). Default to `tool_rich = blue solid`, `bash_only = orange dashed`, `code_only = green dotted`.

---

## Numbers data

Each figure script reads from `paper/data/` (the canonical CSVs) and writes a sidecar `*.numbers.csv` to `paper/generated/figures/` for `build_numbers.py` to pick up. Numbers cited in prose use `\result{fig.signflip}{...}` etc.

| Figure | CSV stem | Generator |
|---|---|---|
| Figure 1 | `fig.01_signflip` | `figures_src/01_signflip.py` |
| Figure 2 | `fig.02_capability_invariance` | `figures_src/02_capability_invariance.py` |
| Figure 3 | `fig.03_cost_decomposition` | `figures_src/03_cost_decomposition.py` |
| Table 1 | (static) | hand-authored in `sections/06_redundancy_table.tex` |
