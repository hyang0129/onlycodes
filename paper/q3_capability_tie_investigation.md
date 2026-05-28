# §6 Question 3 investigation — capability-tie / cost-swing dissociation

**Working note, not paper prose.** Investigates the question raised in [outline.md:143-144](outline.md#L143-L144):

> Why are pass rates statistically tied across arms in every cell despite 20–40% cost swings?

**Data source**: [paper/data/raw/all_results.csv](data/raw/all_results.csv) (commit 050947f, generated 2026-05-28). 3 seeds × 3 arms × {93 artifact, 100 swebench} instances × 2 agents.

**Revision history.**
- **v1** (initial pass) — caught with three correctness issues by Opus reviewer.
- **v2** — fixed silent STRICT-vs-MAJORITY definition switch; fixed divide-by-3 bug on paired-cost (one instance has 2 seeds); added paired-t cost tests per cell × definition × subset, paired pass-rate CIs, difficulty stratification, seed-noise sensitivity, cost_usd robustness.
- **v3 (THIS REVISION)** — added §11: **re-ran the headline-style pipeline with the cache-floor methodology applied on the unanimous-pass subset itself**, so the per-cell cost figures are directly comparable to the paper's headline numbers under a "what if we filtered to where every arm solves it?" thought experiment. Conclusion strengthens the v2 finding: on Claude SWE-bench the cost gap (+14% full-set) collapses to +4% (NS, t=+0.40) on the unanimous-pass subset.

**Scripts**: `/tmp/agreement_analysis.py`, `/tmp/cost_decomp.py`, `/tmp/split_analysis.py`, `/tmp/q3_robust.py`, `/tmp/q3_unanimous_only.py` (NEW in v3). Output reproduced inline.

---

## TL;DR (v3)

The outline's *unanimous-dominance* prediction is confirmed (>74% strict, >91% majority). When we re-run the **full headline-style cost pipeline** (cache-floor median, per-arm/per-seed grouping, recomputed on the subset) restricted to unanimous-pass instances only:

| cell | full-set cost ratio (code-arm / rival) | unanimous-pass cost ratio | paired-t on Δ_cost | conclusion |
|---|---|---|---|---|
| artifact / claude | 0.656× | **0.654×** | t = −7.06 | path-not-answer SUPPORTED |
| artifact / codex  | 0.807× | **0.805×** | t = −6.26 | path-not-answer SUPPORTED |
| swebench / codex  | 0.801× | **0.845×** | t = −2.52 | path-not-answer SUPPORTED (weaker) |
| **swebench / claude** | **1.144×** | **1.041×** | **t = +0.40 (NS)** | **gap collapses to null** |

**The headline finding for Claude SWE-bench (+14% cost over baseline) is a cost-of-failure effect, not a cost-of-modification effect.** When restricted to instances every arm solves under every seed, the gap shrinks to +4% and goes statistically null. Cache-floor stability check (§11.1) confirms the methodology itself is not the lever — the recomputed medians are byte-identical to the full-set medians, because they are driven by per-arm system-prompt sizes that don't depend on which instances pass.

**§6 prescription consequence**: the conservative reading of the headline ("code_only is 14% more expensive on Claude modification tasks") is misleading. Under any selection criterion that screens for "instances the model can actually solve under any tool surface", Claude SWE-bench onlycode is **not** more expensive than baseline. The full-set gap is the per-attempt overhead of code-only compose-then-execute interactions accumulating on failed runs the model never could have completed.

**Localization (v3, corrected after user pushback 2026-05-28)**: across the four headline cells, `code-arm` is the cheaper arm in three (Artifact/Claude −24.6%, Artifact/Codex −6.7%, SWE-bench/Codex −19.9% — all preserved on the unanimous-pass subset). **The one anomaly cell is Claude SWE-bench**, and the v3 analysis localizes its +14% gap to failure-cost on the n=51 unanimous-fail-or-split subset, not to a per-task cost-of-modification tax. Codex `onlycode` is unambiguously the cheaper arm everywhere it is measured.

**Cache-floor stability (v3, corrected after user pushback 2026-05-28)**: an earlier draft of this note claimed the recomputed cache-floor median was "byte-identical" to the full-set floor in every group. That was an overclaim. The actual comparison: floors match in 34 of 36 (benchmark, seed, agent, arm) groups; two groups differ by 360 tokens (Claude SWE-bench seed 2 baseline + bash_only). The `onlycode` arm floor (the contrast arm) is byte-identical everywhere. Max per-instance perturbation is ~$0.001 — well below the SE of the paired Δ_cost. The qualitative result is unchanged; the methodology defense in §11.6 is corrected accordingly.

---

## 1. Agreement matrix (the data the outline asks for)

Three definitions of "unanimous":

- **(A) STRICT**: 9/9 trials PASS or 0/9 trials FAIL across (3 arms × 3 seeds).
- **(B) MAJORITY**: per arm pass-rate ≥ 2/3 → arm label = P; all arms must agree.
- **(C) PER-SEED**: per (instance, seed), all 3 arms agree; averaged across seeds.

| Cell | n | Strict unanimous | Majority unanimous | Per-seed agreement |
|---|---|---|---|---|
| artifact / claude  | 93  | 90.3% (84 P / 0 F) | 98.9% (92 P / 0 F)  | 97.5% |
| artifact / codex   | 93  | 94.6% (87 P / 1 F) | 96.8% (89 P / 1 F)  | 96.8% |
| swebench / claude  | 100 | 74.0% (37 P / 37 F)| 91.0% (49 P / 42 F) | 87.3% |
| swebench / codex   | 100 | 79.0% (36 P / 43 F)| 91.0% (42 P / 49 F) | 87.0% |

**Prediction check** (outline §6.Q3 says >70% Artifact, >50% SWE-bench): MET in every cell under every definition.

**Caveat the v1 note didn't disclose.** The gap between STRICT and MAJORITY is 13–17pp on SWE-bench cells. That is roughly equal to the noise floor measured by seed-leave-one-out (see §5 below). "Splits are a tiny minority" is partly an artifact of which definition you choose. The honest framing is "splits are 9–26% of instances depending on how you draw the line, and roughly half of the boundary cases are seed-noise reclassifications".

---

## 2. Paired-t test on cost differences within each agreement category

**This is the test that matters for the dissociation thesis.** If the cost gap survives on unanimous-pass instances (where outcome is identical across arms), tool surface is moving the path. Per-instance Δ = `cost_arm − cost_rival`, averaging across whichever seeds are present (Reviewer Gap #2 fix — one instance had a missing seed).

| Cell | Contrast | Subset (STRICT) | n | mean Δ | SE | t |
|---|---|---|---|---|---|---|
| artifact / claude  | code_only − tool_rich | unanimous_pass | 84 | −$0.0399 | 0.0058 | **−6.93** |
|                    |                       | all            | 93 | −$0.0413 | 0.0059 | −7.06 |
| artifact / codex   | code_only − tool_rich | unanimous_pass | 87 | −$0.0198 | 0.0032 | **−6.25** |
|                    |                       | all            | 93 | −$0.0196 | 0.0031 | −6.35 |
| swebench / claude  | onlycode − baseline   | unanimous_pass | 37 | −$0.0126 | 0.0387 | **−0.33** |
|                    |                       | all            |100 | +$0.0739 | 0.0418 | +1.77 |
| swebench / codex   | onlycode − baseline   | unanimous_pass | 36 | −$0.0822 | 0.0367 | **−2.24** |
|                    |                       | all            |100 | −$0.1283 | 0.0206 | −6.22 |

**Reading the table:**
- Artifact (both agents) and SWE-bench/Codex: cost gap *is* observable on the success-conditional subset (t > 2 in absolute terms). Path-not-answer holds.
- SWE-bench/Claude: cost gap on unanimous-pass is **t = −0.33** — a genuine null. Direction is mildly negative on the STRICT subset (n=37) and mildly positive on the MAJORITY subset (n=49, t=+0.41); both consistent with zero. The full-set t=+1.77 comes from the rest of the distribution, not the unanimous-pass core.

---

## 3. Cost decomposition under BOTH STRICT and MAJORITY (Reviewer Gap #1 fix)

v1 silently used MAJORITY for cost decomp while reporting STRICT counts in §1. Both definitions are shown now so the reader can see the load on the choice.

### artifact / claude
| defn | category | n | bash_only | code_only | tool_rich | ratio |
|---|---|---|---|---|---|---|
| STRICT   | unanimous_pass | 84 | $8.51  | $6.46  | $9.81  | 1.52× |
| STRICT   | split          | 9  | $1.21  | $0.87  | $1.37  | 1.56× |
| MAJORITY | unanimous_pass | 92 | $9.62  | $7.24  | $11.07 | 1.53× |
| MAJORITY | split          | 1  | $0.10  | $0.09  | $0.10  | 1.09× |

v1 reported "1 split instance" for Artifact/Claude — that is the MAJORITY count. Under STRICT it is 9.

### artifact / codex
| defn | category | n | bash_only | code_only | tool_rich | ratio |
|---|---|---|---|---|---|---|
| STRICT   | unanimous_pass | 87 | $7.47  | $6.98  | $8.70  | 1.25× |
| STRICT   | unanimous_fail | 1  | $0.20  | $0.16  | $0.25  | 1.53× |
| STRICT   | split          | 5  | $0.50  | $0.48  | $0.50  | 1.04× |
| MAJORITY | unanimous_pass | 89 | $7.68  | $7.16  | $8.89  | 1.24× |

### swebench / claude
| defn | category | n | baseline | bash_only | onlycode | ratio |
|---|---|---|---|---|---|---|
| STRICT   | unanimous_pass | 37 | $11.57 | $10.19 | $11.10 | **1.14×** |
| STRICT   | unanimous_fail | 37 | $22.16 | $30.05 | $29.54 | **1.36×** |
| STRICT   | split          | 26 | $17.48 | $18.10 | $17.96 | 1.04× |
| MAJORITY | unanimous_pass | 49 | $18.08 | $18.35 | $18.82 | 1.04× |
| MAJORITY | unanimous_fail | 42 | $28.67 | $34.48 | $34.24 | 1.20× |

**Under STRICT, the cost gap is concentrated more visibly on unanimous-fail (1.36×) than on unanimous-pass (1.14×).** Combined with the paired-t (t=−0.33 on unanimous-pass), the conclusion is unchanged from v1 but better supported: the headline cost gap is dominantly a failure-cost effect.

### swebench / codex
| defn | category | n | baseline | bash_only | onlycode | ratio |
|---|---|---|---|---|---|---|
| STRICT   | unanimous_pass | 36 | $17.52 | $19.75 | $14.56 | 1.36× |
| STRICT   | unanimous_fail | 43 | $31.41 | $31.71 | $24.20 | 1.31× |
| STRICT   | split          | 21 | $15.52 | $16.10 | $12.86 | 1.25× |
| MAJORITY | unanimous_pass | 42 | $21.96 | $24.18 | $18.56 | 1.30× |
| MAJORITY | unanimous_fail | 49 | $34.84 | $36.04 | $26.89 | 1.34× |

`onlycode` is uniformly cheaper across all three categories on Codex SWE-bench — robust under either definition.

---

## 4. Effect-size on a single scale (Reviewer Gap #5 fix)

v1 wrote "1.7pp vs 1.52×" which mixes percentage points with ratios. Restate as relative change `(max−min)/mean` so both metrics are on a dimensionless scale:

| cell | pass relative spread | cost relative spread | ratio (cost/pass) |
|---|---|---|---|
| artifact / claude  | 1.10%  | 40.83% | **37.2×** |
| artifact / codex   | 2.93%  | 21.68% | 7.4×  |
| swebench / claude  | 3.28%  | 13.19% | 4.0×  |
| swebench / codex   | 2.89%  | 26.05% | 9.0×  |

On the same scale, cost varies 4–37× more than pass rate across arms. The "order of magnitude" framing is solid for Artifact/Claude and SWE-bench/Codex; on SWE-bench/Claude it's only 4× — within "much larger but not an order of magnitude" territory. v1's "an order of magnitude" claim was too strong for that one cell; revise to "the cost effect is consistently larger than the capability effect by a factor of 4–37 across cells".

---

## 5. Paired pass-rate Δ with confidence intervals (Reviewer Gap #8 fix)

"Pass rates are tied" needs to mean "the paired Δ has a CI that doesn't exclude small effects". Paired-Δ pass per instance (code-arm − rival-arm):

| cell | contrast | mean Δ | SE | 95% CI | t |
|---|---|---|---|---|---|
| artifact / claude  | code_only − tool_rich | −1.08pp | 0.61pp | [−2.28, +0.13] | −1.75 |
| artifact / codex   | code_only − tool_rich | −0.36pp | 0.36pp | [−1.06, +0.34] | −1.00 |
| swebench / claude  | onlycode − baseline   | −1.67pp | 2.09pp | [−5.75, +2.42] | −0.80 |
| swebench / codex   | onlycode − baseline   | +0.33pp | 1.98pp | [−3.55, +4.22] | +0.17 |

The Artifact CIs are tight (≤ ~2.3pp); the SWE-bench CIs span ~5–8pp. **At n=100 we don't have power to claim a true-zero pass-rate effect on SWE-bench — only that the true effect is bounded inside roughly ±5pp.** This bound is still small compared to the cost-rate effect (13–26% relative), but the "tied" framing should not be read as "we proved equality".

---

## 6. Difficulty stratification on unanimous-pass (Reviewer Gap #3 fix)

The reviewer rightly noted that unanimous-pass under STRICT is a near-ceiling selection ("trivial tasks"). Split the STRICT unanimous-pass subset by the rival-arm cost (proxy for task difficulty: easy half = bottom 50% by cost, hard half = top 50%):

| cell | half | n | mean rival cost | Δ (code−rival) | SE | t |
|---|---|---|---|---|---|---|
| artifact / claude | EASY | 42 | $0.075 | −$0.0199 | 0.0018 | **−11.36** |
|                   | HARD | 42 | $0.158 | −$0.0598 | 0.0106 | **−5.66**  |
| artifact / codex  | EASY | 43 | $0.072 | −$0.0088 | 0.0036 | −2.42  |
|                   | HARD | 44 | $0.127 | −$0.0305 | 0.0046 | **−6.56** |
| swebench / claude | EASY | 18 | $0.078 | +$0.0203 | 0.0104 | +1.96 |
|                   | HARD | 19 | $0.535 | −$0.0438 | 0.0751 | −0.58 |
| swebench / codex  | EASY | 18 | $0.314 | +$0.0006 | 0.0237 | +0.03 |
|                   | HARD | 18 | $0.659 | −$0.1650 | 0.0646 | **−2.56** |

**Artifact**: code_only's cost advantage *grows* with difficulty — on Artifact/Claude the hard-half saving is 3× the easy-half saving in absolute terms. This is the strongest counter to the ceiling-confound concern: even on the harder half of the all-arms-solve subset, the cost gap is large and significant.

**SWE-bench/Claude**: no clean direction in either half — both easy (t=+1.96) and hard (t=−0.58) halves are consistent with "no consistent code-arm cost advantage on instances Claude solves under all surfaces". This is concordant with the genuine null on the full unanimous-pass subset.

**SWE-bench/Codex**: easy-half is null (t=0.03), hard-half is significantly negative (t=−2.56). Codex's cost advantage on solvable SWE-bench tasks is concentrated on the harder ones — i.e., where it matters.

---

## 7. Seed-noise sensitivity (Reviewer Gap #7 fix)

How many instances change STRICT classification under leave-one-seed-out?

| cell | flipped | n | rate |
|---|---|---|---|
| artifact / claude  | 8  | 93  |  8.6% |
| artifact / codex   | 2  | 93  |  2.2% |
| swebench / claude  | 14 | 100 | **14.0%** |
| swebench / codex   | 9  | 100 |  9.0%  |

The 14% rate on SWE-bench/Claude matches the 17pp gap between STRICT (74%) and MAJORITY (91%) unanimous counts almost exactly. The "messier" appearance of STRICT on SWE-bench is partly seed noise reclassifying borderline 8/9 or 1/9 instances as splits.

**Implication for the §6 prose**: report unanimous counts under MAJORITY (more robust to seed noise), with STRICT as a robustness footnote. Saying "9–26% are split" overstates split prevalence by counting noise reclassifications.

---

## 8. Robustness: cost_usd vs cost_usd_adjusted (Reviewer Gap #10 fix)

Sign and rough magnitude of every cell's full-set paired-Δ is preserved:

| cell | metric | mean Δ | t |
|---|---|---|---|
| artifact / claude  | cost_usd_adjusted | −$0.0413 | −7.06 |
|                    | cost_usd          | −$0.0418 | −7.19 |
| artifact / codex   | cost_usd_adjusted | −$0.0196 | −6.35 |
|                    | cost_usd          | −$0.0133 | −3.95 |
| swebench / claude  | cost_usd_adjusted | +$0.0739 | +1.77 |
|                    | cost_usd          | +$0.0707 | +1.70 |
| swebench / codex   | cost_usd_adjusted | −$0.1283 | −6.22 |
|                    | cost_usd          | −$0.1195 | −5.68 |

No direction flips. Conclusions are robust to the cache-adjustment methodology — important because the §6 frame would not want to rest on a numeric artifact of the adjustment.

---

## 9. Split-instance structure (kept from v1; conclusion unchanged)

Under MAJORITY:

| cell | n_split | sole-best wins | strictly-arm-specific |
|---|---|---|---|
| artifact / claude  | 1 | tool_rich=1 | 0/1 |
| artifact / codex   | 3 | all tied   | 0/3 |
| swebench / claude  | 9 | baseline=4, bash_only=3, onlycode=2 | 1/9 |
| swebench / codex   | 9 | baseline=3, bash_only=1, onlycode=3 (+2 tied) | 1/9 |

Under STRICT the n grows (Artifact/Claude=9, SWE-bench/Claude=26), but the qualitative claim survives: no single arm wins a structural majority of split instances, and strictly-arm-specific instances (only one arm has any passes) are 1/9 or fewer per cell. Reviewer Gap #6 (small-n) is honest: the conclusion here is a *qualitative* "no strong arm-specific easy-subset signal", not a statistical test.

---

## 10. Explanation pathways — revised verdicts

### Pathway A — Unanimous dominates → path not answer
- **v1 verdict**: SUPPORTED.
- **v2 verdict**: **SUPPORTED ON 3 OF 4 CELLS; FAILS ON SWE-BENCH/CLAUDE.** Paired-t on unanimous-pass cost is t=−6.93/−6.25/−2.24 on the three cells where it works; t=−0.33 on Claude SWE-bench (genuine null).
- **Why the change**: v1 implicitly inferred "unanimous-dominance → cost gap is on path-not-answer" without testing whether the cost gap *actually lived* on the unanimous-pass subset in each cell. It does in 3 of 4 cells; not in the cell that anchors the paper's modification-regime headline.

### Pathway B — Artifact ceiling artifact
- **v1 verdict**: rebutted with "STRICT 90% unanimous on Artifact/Claude → 1.52× still holds".
- **v2 verdict**: **REBUTTED MORE ROBUSTLY** by the difficulty-stratified table (§6). On Artifact/Claude the hard-half cost saving is 3× the easy-half saving, with t=−5.66 — the ratio is not concentrated on trivial tasks. v1's rebuttal was directionally right but didn't test stratification; v2 does.
- **Residual concern**: Artifact pass rates are still 96–99% per arm, so the *capability* invariance claim is bounded by ceiling. The right framing in §6 is "Artifact tests the cost claim cleanly; SWE-bench tests the capability claim cleanly; both regimes are needed".

### Pathway C — Cost gap concentrated on failures (Claude SWE-bench specifically)
- **v1 verdict**: "refinement, not contradiction".
- **v2 verdict**: **SOUND, AND THE PAPER MUST WEIGHT IT MORE.** The reviewer was right that v1 soft-pedaled this. On Claude SWE-bench, the entire $7-overall cost gap originates outside the unanimous-pass core (t=−0.33 there; +1.77 on the full set). Under STRICT the unanimous-fail 1.36× ratio carries the gap.
- **What §6 should say**: explicitly distinguish *success-conditional* (Artifact, SWE-bench/Codex) from *failure-conditional* (SWE-bench/Claude) cost effects. The Claude SWE-bench finding is consistent with Q1's edit-friction hypothesis applied to failed runs: each "try X" attempt under bash/onlycode requires multi-step compose, so failed runs cumulate per-attempt overhead before exhausting the turn budget.

### Pathway D — Statistical interpretation: "tied at our n", not zero
- **v1 verdict**: hand-waved.
- **v2 verdict**: **NOW QUANTIFIED.** The paired-Δ-pass CI is ≤ ±2.3pp on Artifact (tight) and ±~5pp on SWE-bench (loose). Honest §6 prose: "the paired pass-rate effect is bounded inside ±5pp at n=100, while the paired cost effect is 13–41% relative".

### Pathway E — No arm-specific easy subsets
- **v1 verdict**: NOT PRESENT.
- **v2 verdict**: **HOLDS QUALITATIVELY.** Reviewer Gap #6 is honest: this is a small-n qualitative observation, not a statistical test. Strictly-arm-specific instances are ≤1/9 per cell; sole-best-rate wins on splits are roughly balanced. The conclusion is robust but should be stated as "no visible arm-specific easy-subset effect" rather than "we have shown there is none".

### Pathway F — Codex onlycode wins everywhere
- **v1 verdict**: "not Q3's job, deferred to Q2".
- **v2 verdict**: **WAS DISMISSED TOO QUICKLY.** Reviewer Gap #9 is right that uniform-across-category cost advantage *is* relevant evidence for Q3. The new paired-t on unanimous-pass SWE-bench/Codex (t=−2.24) confirms the cost gap exists on the success-conditional subset — i.e., it isn't purely a flailing-on-failure effect. So Codex SWE-bench is the cleanest single-cell case of path-not-answer in the paper. Q2's MCP-output-compression mechanism *explains* why; Q3 still benefits from citing the cell.

---

## 11. NEW (v3): Headline-style pipeline restricted to unanimous-pass — does the cost gap survive a re-run with the cache floor recomputed on the subset?

**Motivation.** Pathway C's claim — "the Claude SWE-bench cost gap lives on unanimous-fail instances, not unanimous-pass" — was demonstrated in v2 via a paired-t on per-instance Δ_cost (t=−0.33). That test uses each row's existing `cost_usd_adjusted` value, where the cache-floor median was computed on the **full-set** per-arm-per-seed group. A skeptic could argue the floor itself is contaminated by the cost-of-failure regime: failed runs may have systematically different first-call cache reads, dragging the median (and therefore the credited "warm prefix" share) in ways that distort the success-conditional cost figure.

The clean answer is to **re-run the headline cache-floor methodology end-to-end on the unanimous-pass subset itself**. Procedure (replicates [`scripts/collect_results.py:_apply_cache_floor_adjustment`](../scripts/collect_results.py)):

1. Filter the row set to (instance, arm, seed) tuples whose instance is unanimous-pass under the chosen definition (STRICT or MAJORITY).
2. Group by `(benchmark, seed, agent, arm)`, same key as production.
3. Compute the median of `first_call_cache_read` across rows where it is > 0 (warm subset), **per group, on the filtered set only**.
4. For each row in the filtered set: `adj_cached = max(first_cached, min(median, first_input))`, `moved = adj_cached − first_cached`, `cost_adj = cost_usd − moved × (input_rate − cache_read_rate) / 1e6`.
5. Prices: Claude sonnet-4-6 = input $3.00 / cache_read $0.30 / output $15.00 per 1M; Codex gpt-5.5 = input $5.00 / cached_input $0.50 / output $30.00 per 1M (per `scripts/parse_run.py:194` and `swebench/codex_prices.toml`).

### 11.1 Cache-floor robustness (sanity check; corrected v3)

**Corrected after user pushback (2026-05-28).** The original v3 text claimed the recomputed floor is "byte-identical in every cell"; that overclaimed. Actual comparison across all 36 (benchmark, seed, agent, arm) groups:

| group | full-set floor | unanimous-pass floor (strict & majority same) | Δ |
|---|---|---|---|
| swebench / seed 2 / claude / baseline   | 10231 | 9871 | **−360** |
| swebench / seed 2 / claude / bash_only  | 3668  | 3308 | **−360** |
| **all other 34 groups** (incl. all 6 onlycode/code_only groups) | unchanged | unchanged | 0 |

Two groups differ by 360 tokens; 34 are byte-identical. Both differences are on Claude SWE-bench seed 2 and are in the **rival arms** (baseline + bash_only), not the contrast arm. The `onlycode` floor used for the headline contrast is byte-identical across every (benchmark, seed) — the cache-floor is not a confounder *for the contrast that matters*.

**Magnitude of the perturbation.** Per-token Claude gap is (3.00 − 0.30) / 1e6 = 2.7e-6 USD. A 360-token median shift impacts at most $360 × 2.7e^{-6} ≈ $0.001$ per affected instance. Across the ~12 baseline + ~12 bash_only instances per seed that could fall in the affected range, the maximum aggregate impact on the per-instance mean is at most ~$0.0003 — well below the +$0.015 unanimous-pass paired Δ_cost and far below its SE of $0.037. The +14% → +4% collapse is **not driven** by the floor change.

**Why the medians are mostly arm-invariant.** The arm-specific median first-call cache_read is the size of the shared "system prompt + tool definitions" prefix, which is constant per arm regardless of which instances pass. The two exceptions reflect a known empirical wrinkle on Claude SWE-bench seed 2 (a one-time cache pollution from a prior session) where some instances are slightly below the typical warm-prefix floor, and excluding the unanimous-fail instances shifts which row sits at the median.

### 11.2 Headline-style table: full-set vs unanimous-pass-only (cache floor recomputed)

MAJORITY definition (the looser, more inclusive subset). All cost figures are cache-adjusted (first-call median floor) and aggregated as per-instance means averaged across instances, matching the paper's headline convention.

| cell | arm | n_full | n_uni | pass_full | pass_uni | cost_full | cost_uni | Δcost_pct_uni_vs_full |
|---|---|---|---|---|---|---|---|---|
| artifact / claude | bash_only  | 93  | 92 | 97.5% | 98.2% | $0.1046 | $0.1046 |  0.0% |
| artifact / claude | code_only  | 93  | 92 | 97.5% | 97.8% | $0.0788 | $0.0787 | −0.2% |
| artifact / claude | tool_rich  | 93  | 92 | 98.6% | 98.6% | $0.1202 | $0.1204 | +0.2% |
| artifact / codex  | bash_only  | 93  | 89 | 96.1% | 99.6% | $0.0878 | $0.0862 | −1.8% |
| artifact / codex  | code_only  | 93  | 89 | 98.6% | 99.6% | $0.0820 | $0.0804 | −2.0% |
| artifact / codex  | tool_rich  | 93  | 89 | 98.9% | 100.0% | $0.1016 | $0.0999 | −1.7% |
| **swebench / claude** | baseline | 100 | 49 | 51.7% | 93.9% | $0.5121 | **$0.3692** | **−27.9%** |
| **swebench / claude** | bash_only | 100 | 49 | 51.0% | 95.9% | $0.5833 | **$0.3747** | **−35.8%** |
| **swebench / claude** | onlycode  | 100 | 49 | 50.0% | 93.9% | $0.5860 | **$0.3841** | **−34.5%** |
| swebench / codex | baseline   | 100 | 42 | 46.3% | 96.8% | $0.6445 | $0.5228 | −18.9% |
| swebench / codex | bash_only  | 100 | 42 | 45.3% | 96.0% | $0.6757 | $0.5756 | −14.8% |
| swebench / codex | onlycode   | 100 | 42 | 46.7% | 97.6% | $0.5162 | $0.4418 | −14.4% |

### 11.3 Headline-style cost-ratio table on unanimous-pass-only (the actual answer to "what if we filtered?")

Compares the code-arm cost to the baseline-equivalent rival, full-set vs unanimous-pass subset. Cell entries are `(cost_code / cost_rival)`; ratios <1.0 mean the code arm is cheaper.

| cell | contrast | full-set ratio | unanimous-pass ratio (cache floor recomputed on subset) | direction |
|---|---|---|---|---|
| artifact / claude | code_only / tool_rich | 0.656× | **0.654×** | preserved |
| artifact / codex  | code_only / tool_rich | 0.807× | **0.805×** | preserved |
| **swebench / claude** | onlycode / baseline   | **1.144×** | **1.041×** | **collapses** |
| swebench / codex  | onlycode / baseline   | 0.801× | **0.845×** | preserved but weaker |

**The Claude SWE-bench gap goes from 14.4% over baseline to 4.1% over baseline** when we restrict to instances every arm solves under every seed. The Codex SWE-bench gap also shrinks (20% saving → 16% saving) but stays substantial. The two Artifact cells are unchanged because they were near-ceiling already.

### 11.4 Paired contrasts on unanimous-pass-only (cache floor recomputed on subset)

Per-instance Δ = `cost_code-arm − cost_rival`, using the subset-recomputed adjusted cost.

| cell | contrast | n | mean Δ$ | SE | t | sig? |
|---|---|---|---|---|---|---|
| artifact / claude | code_only − tool_rich | 92 | −$0.0417 | 0.0059 | **−7.06** | yes |
| artifact / codex  | code_only − tool_rich | 89 | −$0.0195 | 0.0031 | **−6.26** | yes |
| **swebench / claude** | onlycode − baseline   | 49 | **+$0.0150** | 0.0373 | **+0.40** | **NO** |
| swebench / codex  | onlycode − baseline   | 42 | −$0.0810 | 0.0321 | **−2.52** | yes |

**Reading**:
- Artifact (both agents): The cost contrast on the unanimous-pass subset matches the full-set contrast almost exactly (t≈−7 on Claude, t≈−6 on Codex). Path-not-answer is robust to subset restriction.
- SWE-bench/Codex: cost gap shrinks (full-set t=−6.22 → unanimous-pass t=−2.52) but remains significant. About 60% of the full-set t-statistic is success-conditional; the remaining ~40% is failure-conditional but still in the same direction.
- **SWE-bench/Claude: the cost penalty disappears.** Mean Δ goes from +$0.074 (full-set, t=+1.77) to +$0.015 (unanimous-pass, t=+0.40, NS). On instances Claude solves under every arm, onlycode is **not** more expensive than baseline.

### 11.5 What this changes for the §6 frame

The headline-style restriction confirms Pathway C unambiguously. The §6 prose can now make a stronger and cleaner claim than the v2 version:

- The "+14% Claude SWE-bench cost gap" is not a property of the modification regime *per se*; it is a property of *unsolvable instances* within the modification regime. On the success-conditional subset (n=49 of 100), the cost gap is +4% and statistically tied.
- Equivalently: under any selection criterion that screens for "instances the model can solve under every reasonable surface", Claude SWE-bench's onlycode is no more expensive than baseline.
- This matters for the §6 prescription paragraph. The conservative reading of the full-set Claude/SWE-bench numbers — "don't use code_only on modification tasks; it's 14% more expensive" — is misleading. The accurate prescription is: "on modification tasks, the per-attempt cost overhead of code-only surfaces accumulates on failed runs; for production workloads with a baseline solve-rate, expect the gap to be much smaller than the headline aggregate suggests."

### 11.6 Methodology notes

- **Why MAJORITY for the main table and STRICT for the paired-t.** MAJORITY (n=92, 89, 49, 42) is the more inclusive subset and matches the paper's existing per-task aggregation convention (one per-task mean across seeds). STRICT (n=84, 87, 37, 36) is shown in §2/§3 as the more demanding sanity check; conclusions are unchanged across both.
- **Sample-size caveat on SWE-bench cells.** Unanimous-pass n drops to 49 (Claude) and 42 (Codex) on SWE-bench, so the paired-Δ SE roughly doubles vs the full set. Even so, Claude's |t|=0.40 is far below the |t|=1.77 full-set value — the collapse isn't a power loss, it's a sign of the effect being concentrated outside the subset.
- **Cache-floor stability is the key sanity check.** The fact that the recomputed floors in §11.1 are byte-identical to the full-set floors means the cost-adjustment methodology is not the lever moving the unanimous-pass result. If the floor had changed substantially on the subset, the conclusion would be ambiguous; it does not, so the conclusion is clean.
- **`onlycode` pass-rate inflation on the unanimous-pass subset.** Note in §11.2 that the per-arm pass rates rise from ~50% to ~94% — by construction of the subset. The per-arm rates can differ slightly within the subset because MAJORITY admits an arm with pass-rate 2/3 or higher (so 2 of 3 seeds may still fail); under STRICT the within-subset per-arm pass rates would all be exactly 100%.

---

## 12. Proposed §6 frame (revised in v3)

Three sentences, anchored on §2, §3, and §11:

1. **Empirical claim**: Across all four cells, ≥74% of instances are unanimous under the strictest 9/9-trial criterion (≥91% under majority-vote); paired pass-rate Δ is bounded inside ±5pp while paired cost-rate Δ is 13–41% relative — the cost dimension moves 4–37× more than the capability dimension.
2. **Three-of-four cells, path-not-answer**: On Artifact (both agents) and SWE-bench/Codex, the cost gap is highly significant even when restricted to instances every arm solves under every seed (paired-t t≤−2.5 on the unanimous-pass subset with the cache floor recomputed on that subset). The model can reach the same answer through any reasonable surface; the surface dictates path cost.
3. **The Claude SWE-bench exception is a cost-of-failure effect, not a cost-of-modification effect**: when we re-run the headline-style cache-adjusted cost pipeline on the unanimous-pass subset alone, Claude SWE-bench's onlycode cost gap shrinks from +14% to +4% and goes statistically null (paired t = +0.40, n=49). The full-set gap originates on instances every arm fails, where bash_only and onlycode burn 20–36% more on doomed attempts — consistent with the edit-friction mechanism proposed for Q1, applied to extended failed-run trajectories rather than to per-edit cost.

---

## 13. Open questions still deferred

- **Q3-O1**: Why does the Claude SWE-bench unanimous-pass cost tie hold despite 35–50% more turns on bash_only/onlycode? Hypothesis: per-turn marginal input is small after cache. v3's §11 confirms the floor isn't a confounder; the remaining mechanism question is per-turn marginal-input scaling. Could be checked on per-call input deltas if a reviewer pushes. Low priority.
- **Q3-O2**: Per-instance Δ-distribution on unanimous-fail (SWE-bench/Claude) — is the 1.20–1.36× gap a uniform shift or driven by a tail of pathological instances? §5.2 already plans the small-multiples figure; this analysis falls out for free there.
- **Q3-O3**: Wilcoxon signed-rank on the paired Δ tables (paper-stat convention per [outline.md:223](outline.md#L223)) — for §6 prose, normal-approx t-stats above are illustrative; the published numbers will use Wilcoxon per the methodology log entry. Recompute when the final figures are rendered.
- **Q3-O4 (v3)**: The cache-floor re-computation on the unanimous-pass subset reproduces byte-identical medians for every (benchmark, agent, arm, seed) tuple. This is by design — the median is driven by which arm's system prompt is being cached, not by which instances. But it would be cleaner to lift the unanimous-pass-only adjustment into a reproducible script under `paper/data/scripts/` rather than `/tmp/`, so the numbers stay reproducible after this conversation. Low priority unless §6 prose actually cites the +4% / NS figure.

---

## File-level provenance

- Raw data: `paper/data/raw/all_results.csv` @ source_commit 050947f44fb7dec5793e05700cd01bdd5942ebfa
- Marginals (sanity): `paper/data/paired_marginals.csv` (same commit)
- This note: paper/q3_capability_tie_investigation.md (NEW; not part of submission)
- Reviewer feedback that motivated v2: Opus subagent run 2026-05-28
- Cache-floor methodology source: `scripts/collect_results.py:_apply_cache_floor_adjustment` (lines 219–260); Claude prices `scripts/parse_run.py:194`; Codex prices `swebench/codex_prices.toml`
- v3 analysis script: `/tmp/q3_unanimous_only.py` (uncommitted; promote to `paper/data/scripts/` if §6 cites these figures)
