# Figure Candidates — KDD 2026 SE 3.0 Workshop Submission

Working list. **2026-05-28 revision (rev. 3):** Adds Figures 3 and 4 as §6.2
case-study floats — concrete-instance illustrations of the batching (H1) and
upper-tail-suppression (H2) mechanisms identified in
[q2_token_gap_investigation.md](q2_token_gap_investigation.md) and instantiated
in [investigations/concrete_examples_h1_h2.md](investigations/concrete_examples_h1_h2.md).
These partially supersede the deferred Figure A2 (aggregate CDF / batching) by
making each mechanism concrete on a named instance pair. **Design constraint:
intent-only labeling.** Cards/bars carry *what the agent was trying to do*
(e.g., "find callers", "broad keyword sweep") rather than literal commands or
Python source — the visual punchline is the structural collapse (3 boxes → 1
box; 40k bar → 1.5k bar), not the typography. Cap is now **3 tables + 4
figures**; page-budget impact tracked in Design decisions §6.

**2026-05-28 revision (rev. 2):** §5.4 agreement-matrix + conditional-cost
tables promoted from "deferred appendix" to main-text floats (now Tables 2 and 3) —
they are load-bearing for §6.3's two-mechanism decomposition. Figure 2's framing
shifted from "regime-dependent sign-flip" to "four-cell cost structure" after
sanity-check on Codex (Codex wins both regimes; only Claude flips between regimes,
so the sign-flip is one-cell, not regime-axis). Also, the §3.4 redundancy table is dropped entirely — the empirical mechanism layer in §6 replaces its scaffolding role.

Sources: [outline.md](outline.md) §5–§6, [05_results.md](05_results.md), [06_discussion.md](06_discussion.md).

---

## Cut to ship (3 tables + 2 figures)

These map onto the contribution bullets in [outline.md](outline.md) §1 and the
mechanism questions in [06_discussion.md](06_discussion.md).

### Table 1 — Code-only vs cheapest rival (headline contrasts)

- **Section:** §5.1 (Main Results). LaTeX label `tab:code-only-headline`.
- **Float:** `table*` (two-column-wide). Lives in [sections/05_results.tex](sections/05_results.tex).
- **Content:** 4 rows × (pass Δ pp, cost-adj Δ%, input-tok Δ%, output-tok Δ%) with
  paired Wilcoxon p. Closest-rival contrast per cell: `code_only-vs-bash_only`
  on Artifact, `onlycode-vs-baseline` on SWE-bench.
- **Status:** ✅ wired; data in [data/paired_contrasts.csv](data/paired_contrasts.csv);
  macros `\resp`, `\respp`, `\respct` in [macros.tex](macros.tex).
- **Why:** The numerical headline. Defends the four-cell cost structure and
  the Claude × SWE-bench anomaly. Loads §6.1 (edit friction → output Δ) and
  §6.2 (Codex input-token win).

### Figure 1 — Per-cell Δcost distribution (`fig:cost-distribution`)

- **Section:** §5.2 (Main Results).
- **Float:** `figure` (single-column). Wired in [sections/05_results.tex](sections/05_results.tex).
- **Content:** 2×2 small-multiples panel — one panel per `(benchmark, agent)`
  cell. Each panel: sorted per-instance Δ_cost_adj (code-only − cheapest rival,
  per-instance mean across 3 seeds), with a horizontal zero line and the
  median Δ annotated as a horizontal dashed line. Rows = benchmark (Artifact
  top, SWE-bench bottom); columns = agent (Claude left, Codex right).
- **Status:** ✅ generated → [generated/figures/01_distribution.{pdf,png}](generated/figures/);
  sidecar at [generated/figures/01_distribution.numbers.csv](generated/figures/01_distribution.numbers.csv).
  Script: [figures_src/01_distribution.py](figures_src/01_distribution.py).
- **Why:** Shows the Table 1 means aren't a few-instance fluke. SWE-bench Codex
  panel: 76/100 instances win for `code_only` (uniform shift). SWE-bench
  Claude panel: 44/100 wins with a long right tail (max Δ = +\$2.33) — losses
  are task-structural, anticipating §6.1's edit-friction reading.

### Figure 2 — Four-cell cost structure (`fig:cost-structure`)

- **Section:** §5.3 (Main Results). Label renamed from `fig:signflip` (2026-05-28)
  to reflect the corrected framing — see "Framing change" below.
- **Float:** `figure` (single-column). Wired in [sections/05_results.tex](sections/05_results.tex).
- **Content:** Single panel, 4 bars. Y-axis: cost ratio `code_only / cheapest rival`
  (1.0 horizontal reference line). X-axis: 4 cells grouped as
  `[Artifact-Claude, Artifact-Codex | SWE-bench-Claude, SWE-bench-Codex]`.
  Bars colored by sign and significance; `*` / `**` / `***` / `ns` annotated
  above each bar.
- **Status:** ✅ generated → [generated/figures/02_signflip.{pdf,png}](generated/figures/);
  sidecar at [generated/figures/02_signflip.numbers.csv](generated/figures/02_signflip.numbers.csv).
  Script: [figures_src/02_signflip.py](figures_src/02_signflip.py).
- **Why:** Single visual that exposes the cell-level pattern in 2 seconds —
  3 of 4 cells favor `code_only`; Claude × SWE-bench is the lone exception.
  Defends the agent-conditional-anomaly contribution bullet.
- **Framing change (2026-05-28):** Earlier framing ("regime-dependent sign-flip")
  overstated a Claude-specific phenomenon. Codex actually wins **both**
  regimes (Artifact: 0.93 ns; SWE-bench: 0.80 ***); only Claude shows
  asymmetric direction across regimes. The honest read is "asymmetric anomaly
  with a mechanism account" (§6 unpacks). Underlying script and sidecar CSV
  filenames retain `02_signflip` for stability — only LaTeX label changes.

### Table 2 — Agreement matrix (`tab:agreement-matrix`)

- **Section:** §5.4. Empirical basis for §6.3 (capability-tie mechanism).
- **Float:** `table` (single-column). Wired in [sections/05_results.tex](sections/05_results.tex).
- **Content:** 4 rows × (n, unanimous-majority %, unanimous-strict %,
  split-majority %). Unanimous (majority) ≥ 91% in every cell; strict 9/9
  ≥ 74% in every cell.
- **Status:** ✅ wired; data in [data/agreement_matrix.csv](data/agreement_matrix.csv);
  production script [data/scripts/q3_unanimous_pass.py](data/scripts/q3_unanimous_pass.py).
- **Why:** Promotes capability invariance from "pass rates NS" (Table 1
  column) to "instance-level outcomes are unanimous" — much stronger
  empirical claim. Anchors §6.3's path-not-answer framing.

### Figure 3 — H1 batching: case study (`fig:batching-case`)

- **Section:** §6.2 (Q2 — batching mechanism). Concrete LLM step illustrating
  the aggregate Codex 1.35 → 0.89 tools/LLM-call shift.
- **Float:** `figure` (single-column). Wired in [sections/06_discussion.tex](sections/06_discussion.tex).
- **Source instance:** `sphinx-doc__sphinx-7757`, Codex, seed 3, both arms PASS.
  Rollout excerpts in [investigations/concrete_examples_h1_h2.md](investigations/concrete_examples_h1_h2.md).
- **What the agent was doing:** Gathering context for a fix — needs to see
  the definition site, see how an existing test exercises it, and find other
  callers. Three independent lookups that don't depend on each other.
- **Content (intent-only labels, NOT literal commands).** Vertical two-panel
  diagram of one LLM step:
  - **Top (baseline):** assistant turn → three stacked rounded cards,
    each captioned by *purpose* — "read definition site", "read existing
    test", "search call sites". A tiny grey subtitle on each card cites
    the file (e.g., `sphinx/domains/python.py`) for grounding, but no
    line ranges or command syntax.
  - **Bottom (onlycode):** same assistant turn → a single rounded card
    captioned "one script: read + read + search". Card body shows three
    short stacked intent rows (same wording as the baseline cards) inside
    one outline. No Python source.
- **Visual punchline:** 3 boxes → 1 box, at the same LLM-step boundary.
- **Caption (intent, 1 sentence):** "On a context-gathering step, the
  baseline arm emits three parallel tool calls; the code-only arm bundles
  the same three lookups into a single script."
- **Status:** ❌ to render. Format: inline TikZ in
  [sections/06_discussion.tex](sections/06_discussion.tex) (structural mockup,
  not a data plot — no `figures_src/` script).
- **Why:** §6.2 prose claims the batching mechanism with aggregate ratios;
  reviewers without coding-agent experience need a single LLM-step picture
  to translate "1.35 → 0.89 tools/LLM-call" into a mechanism. Intent-only
  labels keep typography to a minimum so the silhouette dominates.

### Figure 4 — H2 per-call truncation: case study (`fig:truncation-case`)

- **Section:** §6.2 (Q2 — upper-tail-suppression mechanism). Concrete
  illustration of the `exec_command` `max_output_tokens` ceiling pinning.
- **Float:** `figure` (single-column). Wired in [sections/06_discussion.tex](sections/06_discussion.tex).
- **Source instance:** `django__django-11848`, Codex, seed 1, both arms PASS.
  Rollout excerpts in [investigations/concrete_examples_h1_h2.md](investigations/concrete_examples_h1_h2.md).
- **What the agent was doing:** Searching the codebase for the function
  that parses HTTP `Date` headers (`parse_http_date`). The agent needs to
  locate call sites before editing.
- **Content (intent-only labels, NOT literal commands).** Horizontal bar
  chart, x-axis = per-call output character count (0–45,000). Two bars
  for the same logical search step:
  - **Baseline bar:** fills to 40,165 with a red shaded segment past
    40,154 (the `exec_command` cap). Inline annotation at the cap line:
    "cap = 40,154 chars" with a small arrow to a faint "…3 918 tokens
    truncated…" label inside the red segment. Bar label (intent):
    "broad keyword sweep" (small grey subtitle: `rg` over the repo).
  - **Onlycode bar:** fills to 1,514 (visually tiny). Bar label (intent):
    "single-pattern grep" (small grey subtitle: `codebox.grep`).
- **Visual punchline:** the cap line + truncation tail on the baseline
  bar vs. the negligible onlycode bar. The two intent labels explain
  *why* (broad vs. targeted), without showing either regex verbatim.
- **Caption (intent, 1 sentence):** "Searching for call sites of one
  function, the baseline arm's broad pattern matched unrelated fixture
  data and pinned the per-call output cap; the code-only arm's narrower
  pattern returned cleanly."
- **Status:** ❌ to render. Format: matplotlib
  (`figures_src/04_h2_truncation.py`) → PDF + sidecar CSV. Numbers
  (40,165 / 40,154 / 1,514) exposed via `\result{fig.04_h2_truncation}{...}`
  macros so lint guards against drift.
- **Why:** §6.2 prose claims the upper-tail-suppression mechanism with
  aggregate p99 statistics; reviewers need to see the cap-pinning happen
  on a named tool call to believe the mechanism. Intent labels carry the
  *why* — the comparison is broad-vs-targeted scope, not regex syntax.

### Table 3 — Conditional cost (`tab:headline-unanimous`)

- **Section:** §5.4. The v3 finding that decomposes the Claude × SWE-bench anomaly.
- **Float:** `table` (single-column). Wired in [sections/05_results.tex](sections/05_results.tex).
- **Content:** 4 rows × (full-set n, full-set Δcost%, unanimous-pass n,
  unanimous-pass Δcost%, p). Claude × SWE-bench: +14.4% (NS) on full set
  → +4.1% (NS) on unanimous-pass subset. Three of four cells preserve the
  code-arm cost advantage on the subset.
- **Status:** ✅ wired; data in [data/headline_unanimous.csv](data/headline_unanimous.csv);
  same production script as Table 2.
- **Why:** Carries the §6.3 dual-mechanism decomposition (path-cost stays;
  failure-cost collapses). Without this table the §6.3 prose has no
  receipt and §6.6's prescriptions lose their grounding.

---

## Deferred (appendix only if pages allow)

Listed in priority order if any one of them gets a slot back.

### Figure A1 — Edit-friction scatter (`fig:edit-friction-scatter`)

- **Mechanism:** §6.1 (Q1, edit friction).
- **Why deferred:** Per-instance Δ_output_tokens (Claude `code_only` − `baseline`) vs.
  Δ_edit_chars or gold-patch size, Claude SWE-bench only. Headline ρ ≈ 0.49
  (p < 10⁻⁶, n=100). The §6.1 question can be defended via the +40% output-tokens
  cell in Table 1 plus the ρ macro in prose — figure is reinforcement, not load-bearing.
- **Promotion trigger:** reviewer pushback on the edit-friction causal claim.
- **Data:** [data/edit_friction.csv](data/edit_friction.csv) (✅ shipped).
- **Backup form:** 4-bar median-split chart of Δ_output_tokens for
  {Claude, Codex} × {low-patch, high-patch}.

### Figure A2 — MCP output / batching (aggregate) (`fig:mcp-output`)

- **Mechanism:** §6.2 (Q2, batching + upper-tail suppression).
- **Status (rev. 3, 2026-05-28):** Partially superseded by main-text Figures
  3 and 4, which carry the same two mechanisms via concrete case studies.
  This aggregate version is now the *backup* that would land alongside
  reviewer pushback specifically asking for population-level evidence
  (CDFs / ratios across all instances) rather than named instances.
- **Why deferred:** §6.2 makes two claims: (H1) `execute_code` averages more tool
  calls per LLM step (Codex only); (H2) per-call output p99 collapses from the
  `exec_command` ceiling to a paginated regime. Both are testable with a CDF or
  bar chart, but the prose-level macros plus Figures 3 and 4 suffice for the
  §6.2 word budget.
- **Promotion trigger:** reviewer dismisses the case studies as cherry-picked
  and asks for population-level evidence.
- **Data:** TO BE WRITTEN — [data/scripts/mcp_output_size.py](data/scripts/) →
  [data/mcp_output_size.csv](data/) (the §6.2 macros are unresolved until the
  script lands).
- **Backup form:** 4-panel CDF of per-call `function_call_output` size, one
  panel per cell, with the `exec_command` `max_output_tokens` ceiling marked.

### Figure A3 — Agreement-matrix stratified Δcost (`fig:agreement-stratified`)

- **Mechanism:** §6.3 (Q3, capability tie / failure cost).
- **Why deferred:** Tables 2 and 3 already carry the §6.3 evidence. A figure
  would re-present the same numbers with more visual space. Promote only if
  reviewers question whether the per-instance shape supports the
  full-set-vs-unanimous-pass split.
- **Promotion trigger:** reviewer pushes on the dual-mechanism decomposition.
- **Data:** [data/agreement_matrix.csv](data/agreement_matrix.csv) +
  [data/headline_unanimous.csv](data/headline_unanimous.csv) (both ✅) +
  per-instance Δcost from [data/raw/all_results.csv](data/raw/all_results.csv).
- **Backup form:** 4-panel small-multiples (same layout as Figure 1) of
  per-instance Δcost sorted, color-coded by agreement category
  (unanimous-pass / unanimous-fail / split).

---

## Cut entirely

- **Per-regime cost decomposition (was Figure 3).** Original frame
  (per-turn × turn-count) is broken for Codex (always 1 turn). A re-spec
  in terms of input/output tokens duplicates Table 1's last two columns.
- **Agent-surface comparison (was on-bubble).** Fully subsumed by Figure 2's
  4-bar structure.
- **Standalone capability-invariance figure (was Figure A1 pre-rev2).** Promoted
  in spirit to Table 2 (agreement matrix); the standalone bar chart is no
  longer needed.
- **Redundancy table (was §3.4 Table 1).** Dropped 2026-05-28 — the three empirical mechanisms (Q1/Q2/Q3) carry the work the table was operationalizing. `sections/06_redundancy_table.tex` deleted; §3.4 collapses to a single prose paragraph mentioning the Capability Overlap framing (Zhang et al.), with the formal citation living in §2 Related Work.
- **Per-instance cost scatter** and **token-overhead decomposition** —
  redundant or non-load-bearing as before.

---

## Production status

| Float | Status | Production path |
|---|---|---|
| Table 1 | ✅ wired | hand-authored in [sections/05_results.tex](sections/05_results.tex) |
| Figure 1 | ✅ wired | [figures_src/01_distribution.py](figures_src/01_distribution.py) → `make figures` |
| Figure 2 | ✅ wired | [figures_src/02_signflip.py](figures_src/02_signflip.py) → `make figures` |
| Table 2 | ✅ wired | hand-authored in [sections/05_results.tex](sections/05_results.tex); data from [q3_unanimous_pass.py](data/scripts/q3_unanimous_pass.py) |
| Table 3 | ✅ wired | hand-authored in [sections/05_results.tex](sections/05_results.tex); data from same script |
| Figure 3 | ❌ to render | inline TikZ in [sections/06_discussion.tex](sections/06_discussion.tex) (no `figures_src/` script; structural mockup) |
| Figure 4 | ❌ to render | `figures_src/04_h2_truncation.py` → `make figures`; source numbers in [data/h2_truncation_example.csv](data/) (to be authored) |

Five of seven main-text floats are assembled as of 2026-05-28. Remaining gaps:
- Figure 1 / Figure 2 captions in [sections/05_results.tex](sections/05_results.tex) cross-reference `\ref{tab:headline-unanimous}` and `\ref{tab:code-only-headline}` — verify on first build that the labels resolve (they should; all five floats live in the same `.tex` file).
- §5 prose is still TODO — once it lands, Figure 1's caption can sharpen the
  "right-tail loss" reading with a forward-reference to §6.1 by section number.
- Figures 3 and 4 to be rendered per [the rendering plan adjacent to this outline](#rendering-plan-figures-3-and-4) once §6.2 prose is stable enough to anchor the captions.

---

## Design decisions

1. **Y-axis units for Figure 2.** Cost ratio (1.0-anchored) chosen over absolute
   $ or % Δ. Ratio is regime-comparable (cost magnitudes vary 5× between
   Artifact and SWE-bench), and the 1.0 reference line is the visual story.
   % equivalents go in the caption.
2. **Color encoding (Figure 2).** B&W-print-readable: solid bars with significance
   indicated by hatch on NS bars, plus textual `*/**/***/ns` annotations
   above each bar.
3. **Per-instance values for Figure 1.** Cost-adjusted (`cost_usd_adjusted`),
   *not* raw `cost_usd`. The cache-floor adjustment changes the sign of
   exactly one cell (Artifact Codex `code_only` vs `bash_only`) and using the
   adjusted column keeps the figure consistent with Table 1.
4. **§5.4 tables vs. figure.** Two compact `table` floats (single-column)
   chosen over a 4-panel figure because Table 3's contrast is fundamentally
   numerical (full-set vs subset Δ%), not distributional. A figure would
   bury the +14% → +4% collapse that is the §6.3 lede.
5. **Figure 2 label name.** Renamed `fig:signflip` → `fig:cost-structure`
   in the LaTeX to match the corrected framing. The script filename
   (`02_signflip.py`) and sidecar CSV (`02_signflip.numbers.csv`) retain
   the old stem to avoid invalidating the `make values` cache and the
   downstream `\result{fig.02_signflip}{...}` macro keys.
6. **Intent-only labels on Figures 3 and 4 (rev. 3).** Tool-call cards
   and bar labels carry *what the agent was trying to do*, not the
   literal command or regex. The point of the figures is the structural
   collapse (3 boxes → 1; 40k bar → 1.5k); literal command syntax adds
   typography without adding signal, and would force readers to parse
   `rg`/`cat`/`codebox.grep` arguments instead of seeing the silhouette.
   File paths appear only as small grey subtitles for grounding. Verbatim
   excerpts stay in [investigations/concrete_examples_h1_h2.md](investigations/concrete_examples_h1_h2.md).
7. **Page-budget impact of Figures 3 and 4 (rev. 3).** Going from 2 to 4
   figures + 3 tables = 7 floats inside an 8-page workshop ceiling is
   tight. Fallback paths if the layout doesn't accommodate both at
   single-column:
   - **(a) Combine into one `figure*` (two-column-wide) with 1×2 panels**:
     Figure 3 left (tool-card mockup), Figure 4 right (bar chart). Saves
     one float at the cost of cramming the H1 mockup to roughly half
     width. Inline TikZ + matplotlib `\includegraphics` side-by-side
     inside one `figure*`. **Default fallback.**
   - **(b) Move one of A1/A2/A3 further down**: already deferred — no
     additional savings there.
   - **(c) Demote Figure 3 to a `tcolorbox` listing inline in §6.2 prose**:
     not a float, costs no figure slot, but loses the centered visual.
     Use only if `figure*` combine also overflows.
   - **(d) Demote Table 2 or Table 3 to appendix**: not recommended;
     both are load-bearing for §6.3.

---

## Numbers data

Each figure script reads from `paper/data/` and writes a sidecar
`*.numbers.csv` to `paper/generated/figures/`. Caption-cited numbers use
`\result{fig.01_distribution}{...}` / `\result{fig.02_signflip}{...}`.
Table macros pull from the underlying CSV stems directly
(`\result{paired_contrasts}{...}`, `\result{agreement_matrix}{...}`,
`\result{headline_unanimous}{...}`).

| Float | CSV stem | Generator |
|---|---|---|
| Table 1 | `paired_contrasts` | [data/scripts/paired_contrasts.py](data/scripts/paired_contrasts.py) |
| Figure 1 | `fig.01_distribution` | [figures_src/01_distribution.py](figures_src/01_distribution.py) |
| Figure 2 | `fig.02_signflip` | [figures_src/02_signflip.py](figures_src/02_signflip.py) |
| Table 2 | `agreement_matrix` | [data/scripts/q3_unanimous_pass.py](data/scripts/q3_unanimous_pass.py) |
| Table 3 | `headline_unanimous` | [data/scripts/q3_unanimous_pass.py](data/scripts/q3_unanimous_pass.py) |
| Figure 3 | *(none)* | inline TikZ — structural mockup, no numbers to bind |
| Figure 4 | `fig.04_h2_truncation` | [figures_src/04_h2_truncation.py](figures_src/04_h2_truncation.py) (to be authored) |
