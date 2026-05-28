# 05 — Main Results
# THIS IS A DETAILED OUTLINE NOT THE ACTUAL PAPER DRAFT

**Numbers freeze ✅ cleared 2026-05-28.** All 3 seeds × 2 agents × 2 benchmarks landed. §5.1–§5.3 are unblocked; §5.4 is blocked on two CSVs that need to be promoted from the investigation scratch scripts (details at end of §5.4).

**Source-of-truth files.** Every numeric claim in compiled prose must come through `\result{...}` / `\resdelta` / `\resratio` / `\respct` / `\resp` / `\respp` macros backed by these CSVs:

- [paper/data/paired_contrasts.csv](data/paired_contrasts.csv) — key schema `benchmark:agent:contrast:metric`
- [paper/data/paired_marginals.csv](data/paired_marginals.csv) — key schema `benchmark:agent:arm:metric`
- [paper/generated/figures/01_distribution.numbers.csv](generated/figures/01_distribution.numbers.csv) — per-cell distribution stats
- [paper/generated/figures/02_signflip.numbers.csv](generated/figures/02_signflip.numbers.csv) — per-cell ratios + p
- [paper/data/agreement_matrix.csv](data/agreement_matrix.csv) **TO BE WRITTEN**
- [paper/data/headline_unanimous.csv](data/headline_unanimous.csv) **TO BE WRITTEN**

**Section budget.** §5 target 2.0 pg, ceiling 2.15. Per-subsection: §5.1 ≈ 0.5 pg, §5.2 ≈ 0.45 pg, §5.3 ≈ 0.55 pg, §5.4 ≈ 0.40 pg. Total ≈ 1.9 pg.

**What was cut from the pre-2026-05-28 seven-subsection plan.** Standalone capability-invariance subsection (former §5.4) folded into §5.1¶2; per-category and per-repo breakdowns (former §5.5) cut entirely; standalone Codex generalization (former §5.7) folded into §5.3¶2. Rationale in [outline.md](outline.md) §5 and the prose preface to the §5 block. §5.6 (agreement matrix) is renumbered §5.4 — content unchanged.

---

## §5.1 Headline contrasts (~2¶ + Table 1, ~0.5 page)

**Role.** Lands three of the four contribution bullets simultaneously: the regime sign-flip (bullet #2) via the cost-adj column, capability invariance within regime (bullet #3) via the pass column, and agent-design dependence (bullet #4) via the SWE-bench Codex row reversing Claude's direction. Loads §5.2 (distribution check) and §5.3 (visual).

**Table 1.** Already wired in [sections/05_results.tex:14–70](sections/05_results.tex#L14-L70). Four rows (Artifact × {Claude, Codex}, SWE-bench × {Claude, Codex}) × four metric pairs (pass Δ pp, cost-adj Δ%, input-tok Δ%, output-tok Δ%), each with a paired Wilcoxon p. No edits required to the table itself.

### ¶1 — sign-flip on cost-adjusted (~80 words)

**Claim.** Read down Table 1's cost-adj column: Artifact cells show `code_only` cheaper than `bash_only` (the cheapest rival in that regime); SWE-bench cells split — Claude `code_only` is **+14% vs `baseline`** (NS), Codex `code_only` is **−20% vs `baseline`** (p<10⁻⁸). Same model, same harness, same prompts; regime AND agent jointly determine sign.

**Macros to cite (all already exist in Table 1).** Pull the cell values from `paired_contrasts.csv`:
- Artifact / Claude cost-adj: `\respct{paired_contrasts}{artifact:claude:code_only-vs-bash_only:cost_adj:mean_delta}{...:mean_b}` → −24.6%, p = 7.4×10⁻¹⁴ (***)
- Artifact / Codex cost-adj: −6.7%, p = 0.25 (NS, label "directional cheaper")
- SWE-bench / Claude cost-adj: +14.4%, p = 0.12 (NS, label "directional costlier")
- SWE-bench / Codex cost-adj: −19.9%, p = 2.0×10⁻⁹ (***)

**Prose pattern.** Two significant cells with `***` precision; two NS cells with "NS" + directional magnitude in pp%. Do NOT report turns, $/turn, or median-per-instance cost — §3 stipulates the metric surface. Do NOT report raw (non-cache-adjusted) cost — §3.5 stipulates cost-adj is the sole cost column.

### ¶2 — capability invariance + token decomposition (~80 words)

**Claim.** Pass-rate column in Table 1 is NS in all four cells — the sign-flip on cost lives in *how* the agent arrives at the answer, not whether it arrives. Token columns localize the cost asymmetry: Claude SWE-bench's +14% cost overrun is concentrated in **+40% output tokens** (p < 10⁻⁹), foreshadowing §6.1 (edit friction); Codex SWE-bench's −20% cost win is concentrated in **−25% input tokens** with output flat (NS), foreshadowing §6.2 (per-call input budget). Two arms in the same regime arrive at opposite costs via opposite token surfaces.

**Macros to cite.**
- Aggregate pass-NS claim: cite the four `\resp{paired_contrasts}{...:pass:wilcoxon_p}` p-values implicitly via "all four NS" — no need to re-quote each value (it's in the table).
- Claude SWE-bench output Δ: `\respct{paired_contrasts}{swebench:claude:onlycode-vs-baseline:output_tokens:mean_delta}{...:mean_b}` → +39.9%; p = `\resp{...:output_tokens:wilcoxon_p}` → 4.8×10⁻¹⁰.
- Codex SWE-bench input Δ: `\respct{paired_contrasts}{swebench:codex:onlycode-vs-baseline:input_tokens:mean_delta}{...:mean_b}` → −24.8%; p = `\resp{...:input_tokens:wilcoxon_p}` → 6.0×10⁻⁹.

**Forward-reference handling.** One sentence each pointing to §6.1 and §6.2; do not preview the mechanism content. The §5.1¶2 sentence stops at "token columns localize the gap to opposite surfaces in the two SWE-bench cells; §6.1 and §6.2 unpack the mechanisms."

---

## §5.2 Per-cell Δ distribution (Figure 1, ~1¶, ~0.45 page)

**Role.** Defends Table 1 means against the "few outliers" attack — and pre-empts §6.1 by showing the Claude SWE-bench loss has structural distribution shape (right-tail loss), not noise. Numbers come from `01_distribution.numbers.csv`, not recomputed.

**Figure 1.** 2×2 small-multiples panel of sorted per-instance Δcost_adj (code_only − cheapest rival, per-instance mean across 3 seeds). Already generated at [paper/generated/figures/01_distribution.{pdf,png}](generated/figures/). No edits required.

### ¶1 — distributional reading (~110 words)

**Claim.** Artifact-Claude: `\result{fig.01_distribution}{artifact-claude:n_win}` / 93 instances win for `code_only` (median Δ = `\result{fig.01_distribution}{artifact-claude:median_delta}` USD) — a uniform shift, not an outlier-driven mean. SWE-bench-Codex: `\result{fig.01_distribution}{swebench-codex:n_win}` / 100 instances win (median = `\result{fig.01_distribution}{swebench-codex:median_delta}` USD) — also a uniform shift. SWE-bench-Claude inverts: only `\result{fig.01_distribution}{swebench-claude:n_win}` / 100 wins, and the loss is **concentrated in a right tail** (max Δ = `\result{fig.01_distribution}{swebench-claude:max_delta}` USD, p75 = `\result{fig.01_distribution}{swebench-claude:p75_delta}` USD) — losses are task-structural, anticipating §6.1's edit-friction reading. Artifact-Codex is symmetric near zero (`\result{fig.01_distribution}{artifact-codex:n_win}` / 93 wins, IQR `\result{fig.01_distribution}{artifact-codex:p25_delta}` to `\result{fig.01_distribution}{artifact-codex:p75_delta}` USD) — consistent with the NS Table 1 row.

**Macros to cite.** All five stats per cell from `01_distribution.numbers.csv` (`n_win`, `median_delta`, `p25_delta`, `p75_delta`, `max_delta`). Quote `n_win` for all four cells, `median_delta` for the two decisive cells (artifact-claude, swebench-codex), and the tail/IQR descriptors for the two asymmetric-or-NS cells (swebench-claude right tail, artifact-codex IQR).

**Prose pattern.** One sentence per cell; organize Artifact row first, then SWE-bench row. Closing sentence: "the distribution shapes in panels (c) and (d) anticipate §6's two mechanism questions — Claude's right-tail loss on SWE-bench (§6.1) and Codex's uniform win on SWE-bench (§6.2)."

---

## §5.3 Sign-flip + agent-flip (Figure 2, ~2¶, ~0.55 page)

**Role.** Visual headline — turns Table 1's four numbers into one panel that a reviewer reads in 2 seconds. Also lands the contribution bullet #4 elevation: optimal surface is jointly determined by regime AND agent design (was "secondary," now co-headline).

**Figure 2.** Single panel, 4 bars: cost ratio `code_only / cheapest rival` per cell, 1.0 reference line. Already generated at [paper/generated/figures/02_signflip.{pdf,png}](generated/figures/). No edits required.

### ¶1 — Figure 2 walkthrough (~70 words)

**Claim.** Read the four bars left-to-right: Artifact-Claude ratio = `\result{fig.02_signflip}{artifact-claude:ratio}` (***, p = `\result{fig.02_signflip}{artifact-claude:p}`); Artifact-Codex `\result{fig.02_signflip}{artifact-codex:ratio}` (ns); SWE-bench-Claude `\result{fig.02_signflip}{swebench-claude:ratio}` (ns, directional loss); SWE-bench-Codex `\result{fig.02_signflip}{swebench-codex:ratio}` (***, p = `\result{fig.02_signflip}{swebench-codex:p}`). The 1.0 reference line is crossed by the SWE-bench Claude bar alone.

**Macros to cite.** Four ratios + four p-values from `02_signflip.numbers.csv`. The `***` / `ns` annotation is already baked into the figure caption; prose mirrors it.

### ¶2 — agent-design dependence (~80 words)

**Claim.** SWE-bench Claude `code_only` is the *only* cell where restricting to `execute_code` makes the agent costlier than its cheapest rival; SWE-bench Codex is the cell where the same restriction yields the **largest** cost win in the matrix. Same restriction, opposite direction — surface choice is jointly determined by regime AND agent design (the §1 contribution bullet #4 framing). §6.1 explains the Claude direction (edit friction on Edit/Write-heavy tasks); §6.2 explains the Codex direction (tool-call batching + upper-tail output suppression). §5.3 stops at "the two cells need separate explanations"; the explanations live in §6.

**Macros to cite.** Reuse `\result{fig.02_signflip}{swebench-claude:ratio}` and `\result{fig.02_signflip}{swebench-codex:ratio}` from ¶1 to anchor the contrast — no new macros.

**Forward-reference handling.** Two sentences, one each pointing to §6.1 and §6.2. Do NOT preview either mechanism; that's what §6 is for.

---

## §5.4 Agreement matrix + conditional cost (~120 words / ~0.40 page)

*(Renumbered from former §5.6; content unchanged.)*

**Role.** §5.4 supplies the empirical basis for §6.3 (the Q3 mechanism question). It answers "how often do the three arms agree on pass/fail per instance, and what does the cost gap look like when restricted to instances every arm solves?"

**Two reportable outputs:**

1. **Per-cell unanimous-pass / unanimous-fail / split counts.** Three definitions, but the published table uses MAJORITY (per arm pass-rate ≥ 2/3) for headline numbers because it is robust to seed-noise reclassification (~14% of Claude SWE-bench classifications flip under leave-one-seed-out). STRICT (9/9 trials) reported as a robustness column.

| Cell | n | Unanimous (majority) | Strict 9/9 | Split (majority) |
|---|---|---|---|---|
| Artifact / Claude | 93 | `\result{agreement_matrix}{artifact_claude_unanimous_majority_pct}` | `\result{agreement_matrix}{artifact_claude_unanimous_strict_pct}` | `\result{agreement_matrix}{artifact_claude_split_majority_pct}` |
| Artifact / Codex  | 93 | `\result{agreement_matrix}{artifact_codex_unanimous_majority_pct}`  | `\result{agreement_matrix}{artifact_codex_unanimous_strict_pct}`  | `\result{agreement_matrix}{artifact_codex_split_majority_pct}` |
| SWE-bench / Claude| 100| `\result{agreement_matrix}{swebench_claude_unanimous_majority_pct}` | `\result{agreement_matrix}{swebench_claude_unanimous_strict_pct}` | `\result{agreement_matrix}{swebench_claude_split_majority_pct}` |
| SWE-bench / Codex | 100| `\result{agreement_matrix}{swebench_codex_unanimous_majority_pct}`  | `\result{agreement_matrix}{swebench_codex_unanimous_strict_pct}`  | `\result{agreement_matrix}{swebench_codex_split_majority_pct}` |

Note in caption: under STRICT, splits are 9.7–26.0% across cells; under MAJORITY they are 1.1–9.0%. The ~13pp gap on SWE-bench cells matches the seed-leave-one-out reclassification rate, so MAJORITY counts the "stable" splits and STRICT counts both stable and noise-driven splits.

One sentence on split structure: only `\result{agreement_matrix}{swebench_claude_strictly_arm_specific_count}` of `\result{agreement_matrix}{swebench_claude_split_majority_count}` split instances on Claude SWE-bench have a single arm carrying all the passes — splits are graded-difficulty mixes near each cell's solvability boundary, not arm-specific easy-subsets. Numerical claim only; no figure.

2. **Conditional-cost row pair** (the v3 finding). For each (benchmark, agent) cell, report the full-set headline cost contrast alongside the unanimous-pass-conditional contrast:

| Cell | Contrast (code-arm − rival) | n | Full-set Δcost adj. | Unanimous-pass Δcost adj. |
|---|---|---|---|---|
| Artifact / Claude  | code_only − bash_only | 93 → 92 | `\result{headline_unanimous}{artifact_claude_cost_adj_full_pct}`     | `\result{headline_unanimous}{artifact_claude_cost_adj_unanimous_pct}` |
| Artifact / Codex   | code_only − bash_only | 93 → 89 | `\result{headline_unanimous}{artifact_codex_cost_adj_full_pct}`      | `\result{headline_unanimous}{artifact_codex_cost_adj_unanimous_pct}` |
| SWE-bench / Claude | onlycode − baseline   | 100 → 49 | **`\result{headline_unanimous}{swebench_claude_cost_adj_full_pct}` (NS)** | **`\result{headline_unanimous}{swebench_claude_cost_adj_unanimous_pct}` (NS)** |
| SWE-bench / Codex  | onlycode − baseline   | 100 → 42 | `\result{headline_unanimous}{swebench_codex_cost_adj_full_pct}`      | `\result{headline_unanimous}{swebench_codex_cost_adj_unanimous_pct}` |

**Caption must say:** unanimous-pass-conditional contrast is computed with the **cache-floor median recomputed on the subset** per the §3.5 methodology (not the full-set floor reused on the subset). Cache-floor stability across the two: matches in `\result{agreement_matrix}{cache_floor_unchanged_groups}` of `\result{agreement_matrix}{cache_floor_total_groups}` (benchmark, seed, agent, arm) groups; the two exceptions are Claude SWE-bench seed 2 baseline + bash_only (rival arms, not the contrast arm), with ≤$0.001/instance perturbation.

**Reading (one sentence, compiled prose):** in 3 of 4 cells the cost gap is preserved on the unanimous-pass subset (Artifact × {Claude, Codex} and SWE-bench/Codex), supporting the "tool surface = path, not answer" reading; in the Claude SWE-bench cell the +14% gap collapses to +4% NS, indicating the full-set gap is a failure-cost effect (mechanism analyzed in §6.3).

**Figure decision.** *No dedicated figure for §5.4.* The two small tables above are the content; promoting them to a figure would not buy additional visual signal. Reserved appendix figure if a reviewer pushes back: 4-panel small-multiples of per-instance Δcost (code-arm − rival) sorted, color-coded by agreement category — the same structure as Figure 1 (§5.2) but stratified by unanimous-pass / unanimous-fail / split. Production script: `paper/data/scripts/q3_unanimous_pass.py` (TO BE WRITTEN; promote `/tmp/q3_unanimous_only.py` and `/tmp/q3_headline_compare.py`).

**Numbers source-of-truth:** [`paper/data/agreement_matrix.csv`](data/agreement_matrix.csv) (per-cell unanimous counts, split structure, cache-floor stability metrics); [`paper/data/headline_unanimous.csv`](data/headline_unanimous.csv) (full-set vs unanimous-pass-subset contrast metrics in the same layout as `paired_contrasts.csv`). Both files **TO BE WRITTEN** — pre-condition for §5.4 prose drafting.

**Investigation note (full data trail):** [`paper/q3_capability_tie_investigation.md`](q3_capability_tie_investigation.md) §1–§11 (v3, corrected after Opus reviewer + user pushback 2026-05-28). §11 is the canonical conditional-cost analysis; §11.1 documents the cache-floor robustness check.

---

## Pre-drafting checklist

Before any subsection here can become LaTeX prose in [sections/05_results.tex](sections/05_results.tex):

- [x] **§5.1** — Table 1 already wired (`tab:code-only-headline`); macros already exist. Drafting ¶1 + ¶2 directly from this outline. No prerequisite.
- [x] **§5.2** — Figure 1 already generated; `01_distribution.numbers.csv` exists and is loaded by the build pipeline. Drafting ¶1 directly. No prerequisite.
- [x] **§5.3** — Figure 2 already generated; `02_signflip.numbers.csv` exists and is loaded by the build pipeline. Drafting ¶1 + ¶2 directly. No prerequisite.
- [ ] **§5.4** — *blocked*: need `paper/data/agreement_matrix.csv` and `paper/data/headline_unanimous.csv` to exist before prose can land. Production script promotion (`paper/data/scripts/q3_unanimous_pass.py` from `/tmp/q3_unanimous_only.py` + `/tmp/q3_headline_compare.py`) is the unblock step. Numbers themselves exist in [`q3_capability_tie_investigation.md`](q3_capability_tie_investigation.md) §11 — promotion is mechanical, not analytical.

§5.1–§5.3 can be drafted in parallel, independently of §5.4. §5.4 cannot begin until the two CSVs land.

---

## Downstream edits triggered by this restructure (for future agents)

Folding former §5.4 / §5.5 / §5.7 and renumbering former §5.6 → §5.4 invalidates forward-references in other paper files. Apply when those files are next touched:

- [03_method.md](03_method.md) line 90: drop the sentence "§5.4 reports per-category pass/cost" — per-category §5.5 is cut.
- [04_experimental_setup.md](04_experimental_setup.md) lines 16, 18: drop the trailing clauses "per-category pass/cost is reported in §5.4" and "per-repo breakdowns appear in §5.4" — those subsections no longer exist.
- [04_experimental_setup.md](04_experimental_setup.md) line 26: "Codex is reported as a generalization probe in §5.6" → "Codex is reported as a co-headline finding in §5.3" (Figure 2's 4-bar).
- [06_discussion.md](06_discussion.md) lines 30, 53, 99 (§5.6 references): retarget to §5.4.

Not applied in this commit — flagged here for the editor of those files.
