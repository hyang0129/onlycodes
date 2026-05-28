# Figure Candidates — KDD 2026 SE 3.0 Workshop Submission

Working list. **2026-05-28 revision:** scoped to **Table 1 + Figure 1 + Figure 2** —
the four cells × multiple metrics produce more visual claims than 8 pages can
absorb, and the cleaner story is one rigorous headline table plus two figures
that each defend a distinct claim. Other candidates (capability invariance,
agreement matrix, edit-friction scatter, cost decomposition) are tracked
below as **deferred** — they get appendix slots only if space allows after the
prose stabilises.

Sources: [outline.md](outline.md) §5–§6.

---

## Cut to ship (1 table + 2 figures)

These map onto the contribution bullets in [outline.md](outline.md) §1 and the
mechanism questions in §6.

### Table 1 — Code-only vs cheapest rival (headline contrasts)

- **Section:** §5.1 (Main Results). LaTeX label `tab:code-only-headline`.
- **Content:** 4 rows × (pass Δ, cost-adj Δ%, input-tok Δ%, output-tok Δ%) with
  paired Wilcoxon p. Closest-rival contrast per cell: `code_only-vs-bash_only`
  on Artifact, `onlycode-vs-baseline` on SWE-bench.
- **Status:** ✅ implemented in [sections/05_results.tex](sections/05_results.tex);
  data in [data/paired_contrasts.csv](data/paired_contrasts.csv); macros
  `\resp`, `\respp`, `\respct` in [macros.tex](macros.tex).
- **Why:** The numerical headline. Defends both the regime-flip framing and
  the agent-flip refinement (Codex onlycode wins SWE-bench; Claude onlycode
  loses). Loads §6 mechanism questions 1 and 2.

### Figure 1 — Per-cell Δ distribution

- **Section:** §5.2 (Main Results). LaTeX label `fig:cost-distribution`.
- **Content:** 2×2 small-multiples panel — one panel per `(benchmark, agent)`
  cell. Each panel: sorted per-instance Δ_cost_adj (code-only − cheapest rival,
  per-instance mean across 3 seeds), with a horizontal zero line and the
  median Δ annotated as a horizontal dashed line. Rows = benchmark (Artifact
  top, SWE-bench bottom); columns = agent (Claude left, Codex right).
- **Why:** Shows the headline Δ in Table 1 isn't a few-instance fluke. The
  anticipated reading: SWE-bench Codex panel is asymmetric (long left tail —
  big wins on sphinx/sympy/xarray, small losses elsewhere); SWE-bench Claude
  panel is the opposite skew (long right tail — edit-heavy tasks make
  `onlycode` more expensive). Motivates §6 question 1 (edit friction) by
  showing the loss is task-structural, not random.
- **Data:** [data/raw/all_results.csv](data/raw/all_results.csv) (per-instance
  costs); cheapest rival per cell hardcoded in the script (matches Table 1).
- **Script:** `figures_src/01_distribution.py`. Sidecar:
  `generated/figures/01_distribution.numbers.csv`.

### Figure 2 — Sign-flip headline (4-bar)

- **Section:** §5.3 (Main Results). LaTeX label `fig:signflip`.
- **Content:** Single panel, 4 bars. Y-axis: cost ratio `code_only / rival`
  (1.0 horizontal reference line). X-axis: 4 cells grouped as
  `[Artifact-Claude, Artifact-Codex | SWE-bench-Claude, SWE-bench-Codex]`.
  Bars colored by sign and significance:
  green-solid (<1.0 with p<0.05), grey (NS), red-solid (>1.0 with p<0.05).
  Significance annotated above each bar via `*` / `**` / `***` / `ns`.
- **Why:** The single visual that exposes the **agent-dependent flip** on
  SWE-bench: Claude bar `>1.0` (code-only loses), Codex bar `<1.0`
  (code-only wins) — the same restriction does opposite things to the
  two agents. Defends contribution bullet on agent-design dependence.
- **Data:** [data/paired_marginals.csv](data/paired_marginals.csv) (per-arm
  means) + [data/paired_contrasts.csv](data/paired_contrasts.csv) (p-values).
- **Script:** `figures_src/02_signflip.py`. Sidecar:
  `generated/figures/02_signflip.numbers.csv`.

---

## Deferred (appendix only if pages allow)

These were in the original cut but lose to the headline three under the
revised 8-page budget. Listed in priority order if any one of them gets a
slot back.

### Figure A1 — Capability invariance (was Figure 2)
- **Why deferred:** Same claim is already visible in Table 1's pass column
  (all four cells show pass Δ NS). A standalone bar chart adds visual weight
  but no new information. Could come back if a reviewer asks "but pass rate
  variance per instance might matter."

### Figure A2 — Agreement matrix (was on-bubble Figure 4)
- **Why deferred:** Anchors §6 question 3 (capability vs harness dissociation)
  but the question can be defended in prose with the pass-rate numbers from
  Table 1 + a single sentence citing the unanimous fraction. Promote to
  appendix figure if the §6 question becomes load-bearing.

### Figure A3 — Edit-friction correlate (new candidate for §6 Q1)
- **Why deferred:** Per-instance Δ_cost vs gold-patch size, Claude SWE-bench
  only. Needs a join with `problems/swe/*/<id>.yaml`. Strong but the §6
  question can also be defended via the +40% output-tokens observation alone
  (already in Table 1). Promote if Figure A1/A2 don't earn their slots.

### Cut entirely
- **Per-regime cost decomposition (was Figure 3).** Original frame
  (per-turn × turn-count) is broken for Codex (always 1 turn). A re-spec
  in terms of input/output tokens duplicates Table 1's last two columns.
- **Agent-surface comparison (was on-bubble).** Fully subsumed by the new
  4-bar sign-flip in Figure 2.
- **IDE primitive ↔ bash redundancy table.** Kept as inline `tabular` in
  [sections/06_redundancy_table.tex](sections/06_redundancy_table.tex);
  no longer numbered as a top-level table.
- **Per-instance cost scatter** and **token-overhead decomposition** —
  redundant or non-load-bearing as before.

---

## Production order

1. ✅ Table 1 — implemented and verified through `make values`.
2. **Figure 1** — produce now. Data ready in
   [data/raw/all_results.csv](data/raw/all_results.csv).
3. **Figure 2** — produce now. Data ready in
   [data/paired_marginals.csv](data/paired_marginals.csv) and
   [data/paired_contrasts.csv](data/paired_contrasts.csv).

---

## Design decisions

1. **Y-axis units for Figure 2.** Cost ratio (1.0-anchored) chosen over absolute
   $ or % Δ. Ratio is regime-comparable (cost magnitudes vary 5× between
   Artifact and SWE-bench), and the 1.0 reference line is the visual story.
   % equivalents go in the caption.
2. **Color encoding.** B&W-print-readable: solid bars with significance
   indicated by hatch on NS bars, plus textual `*/**/***/ns` annotations
   above each bar.
3. **Per-instance values for Figure 1.** Cost-adjusted (`cost_usd_adjusted`),
   *not* raw `cost_usd`. The cache-floor adjustment changes the sign of
   exactly one cell (Artifact Codex `code_only` vs `bash_only`) and using the
   adjusted column keeps the figure consistent with Table 1.

---

## Numbers data

Each figure script reads from `paper/data/` and writes a sidecar
`*.numbers.csv` to `paper/generated/figures/`. Caption-cited numbers use
`\result{fig.01_distribution}{...}` / `\result{fig.02_signflip}{...}`.

| Figure | CSV stem | Generator |
|---|---|---|
| Figure 1 | `fig.01_distribution` | `figures_src/01_distribution.py` |
| Figure 2 | `fig.02_signflip` | `figures_src/02_signflip.py` |
