# Edit-friction hypothesis — investigation

**Question (from `paper/outline.md` line 139):** Why does Claude struggle with `onlycode` on SWE-bench? Specifically, Claude SWE-bench `onlycode` is the only cell where code-only loses; cost runs +14% (NS) vs baseline and **output tokens are +40% (p<10⁻⁹)** vs baseline.

**Working hypothesis:** *Edit friction.* SWE-bench requires many small file edits. Claude's `baseline` arm uses native `Edit`/`Write` tools (cheap per call); `onlycode` forces it to write full Python `pathlib`/`re.sub` scripts to achieve the same effect — generating proportionally more output tokens per edit.

**Data sources (all paper-scope):**
- Per-instance metrics: `paper/data/raw/all_results.csv` (n = 100 SWE-bench instances × 3 arms × 1 seed for Claude; same for Codex).
- Marginal/contrast tables: `paper/data/paired_marginals.csv`, `paper/data/paired_contrasts.csv`.
- Gold patches: pulled from HuggingFace (`princeton-nlp/SWE-bench_Verified` + `SWE-bench`) — explicitly named in the user prompt, so within scope. Joined to per-instance Δ in [`edit_friction_data.csv`](edit_friction_data.csv).
- Scripts: [`edit_friction_analysis.py`](edit_friction_analysis.py) (primary Spearman), [`edit_friction_v2.py`](edit_friction_v2.py) (within-arm slopes, median split, partial correlation).

Patch-size proxies used:
- `patch_lines_added` — number of `+` lines in the gold patch (test patch excluded).
- `patch_lines_changed` — `+` plus `-` lines.
- `patch_files_touched` — distinct files modified.

---

## Pathway 1 — Edit friction (primary hypothesis)

**Prediction:** per-instance Δ (onlycode − baseline) for output tokens and cost rises with gold-patch size for **Claude** SWE-bench, but not for **Codex** SWE-bench (Codex baseline doesn't have native Edit, so onlycode shouldn't lose a tool it never used).

### Test (a) — Spearman correlation of Δ vs patch size

Claude SWE-bench, Δ = onlycode − baseline, n = 100:

| metric | vs `patch_lines_added` | vs `patch_lines_changed` | vs `patch_files_touched` |
|---|---|---|---|
| output_tokens | ρ = **+0.228**, p = 0.023 * | ρ = +0.210, p = 0.036 * | ρ = +0.222, p = 0.027 * |
| cost_usd | ρ = +0.203, p = 0.043 * | ρ = +0.184, p = 0.066 | ρ = +0.162, p = 0.11 |
| cost_usd_adjusted | ρ = +0.213, p = 0.033 * | ρ = +0.196, p = 0.051 | ρ = +0.173, p = 0.085 |
| num_turns | ρ = +0.257, p = 0.010 ** | ρ = +0.234, p = 0.019 * | ρ = **+0.301**, p = 0.002 ** |
| llm_calls | ρ = +0.132, p = 0.19 | ρ = +0.104, p = 0.30 | ρ = +0.133, p = 0.19 |

**All seven significant correlations are positive**, and the strongest signal (ρ = +0.301 for files-touched vs Δturns) is in the expected direction.

Codex SWE-bench, Δ = onlycode − baseline (placebo):

| metric | vs `patch_lines_added` |
|---|---|
| output_tokens | ρ = −0.134, p = 0.18 (NS) |
| cost_usd | ρ = −0.197, p = 0.049 * (opposite sign!) |
| num_turns | n/a (Codex always 1 turn) |

**Codex shows no positive correlation**; if anything the direction flips. Marginal Δ_output_tokens for Codex onlycode−baseline is +35 tokens (NS, p = 0.83) — flat — so the placebo holds.

### Test (a') — Within-arm OLS slope (stronger signal than Spearman)

Output tokens regressed on `patch_lines_added` *within each arm*:

| agent | arm | slope (tok/line) | R² | n |
|---|---|---:|---:|---:|
| claude | baseline | **+7.5** | 0.001 | 100 |
| claude | onlycode | **+26.9** | 0.007 | 100 |
| claude | bash_only | +19.1 | 0.004 | 100 |
| codex | baseline | +4.4 | 0.012 | 100 |
| codex | onlycode | +2.5 | 0.004 | 100 |
| codex | bash_only | +2.6 | 0.004 | 100 |

Bootstrap CI for slope(onlycode) − slope(baseline):
- **Claude: +36.2 tok/line, 95% CI [+3.4, +129.1]** — CI excludes 0.
- **Codex: −1.9 tok/line, 95% CI [−6.2, +2.8]** — CI includes 0.

Interpretation: Claude `onlycode`'s per-line edit tax is ~3.6× baseline's. Codex shows no such tax differential (both arms produce ~constant ~3 tok/line). The slope gradient on Claude — **baseline 7.5 → bash_only 19.1 → onlycode 26.9** — matches the verbosity ordering of edit primitives (native `Edit` < `sed`/heredoc < `pathlib`/`re.sub` Python scripts), supporting the mechanism.

### Test (b) — Cross-cell sanity (Claude artifact)

If edit friction is real, it should be **absent** on artifact tasks (which generate single Python scripts, no in-place edits). Looking at marginal Δ from [`paired_contrasts.csv`](../data/paired_contrasts.csv):

| benchmark | contrast (Claude) | Δ output tokens | Wilcoxon p |
|---|---|---:|---:|
| SWE-bench | onlycode − baseline | **+4,440 (+40%)** | p = 5×10⁻¹⁰ *** |
| Artifact | code_only − tool_rich | −605 (−20%) | p = 0.14 (NS) |

And on cost:

| benchmark | contrast (Claude) | Δ cost (USD) | Wilcoxon p |
|---|---|---:|---:|
| SWE-bench | onlycode − baseline | +$0.071 (+14%) | p = 0.21 (NS) |
| Artifact | code_only − tool_rich | **−$0.042 (−34%)** | p = 3×10⁻¹⁶ *** |

**On artifact, code_only WINS on cost and shows no output-token tax** — exactly the opposite of SWE-bench. Consistent with edit friction being SWE-bench-specific.

### Test (c) — Cross-agent sanity (Codex)

Already covered above. Codex onlycode−baseline Δ_output_tokens is +35 (NS); the per-line slope difference is −1.9 (CI includes 0); median-split shows no high-vs-low effect. Codex never had native Edit to lose, so the prediction of no edit-friction is confirmed.

### Test (a'') — Median-split contrast (Claude SWE-bench)

Split instances at the median patch size (6 lines):

| half | n | mean Δ_output_tokens (onlycode − baseline) | Wilcoxon p |
|---|---:|---:|---:|
| low patch (≤6 lines) | 52 | **+2,650** ± 954 | 2×10⁻⁵ |
| high patch (>6 lines) | 48 | **+6,378** ± 1,602 | 7×10⁻⁷ |
| one-sided Mann-Whitney high > low | | | **p = 0.025** |

**The onlycode penalty is 2.4× larger on the high-patch half.** Both halves are individually significant (so onlycode pays a tax even on small patches), but the tax grows with patch size in the predicted direction.

### Test (a''') — Partial correlation controlling for baseline difficulty

Confound: bigger patches may simply be harder tasks, producing more output tokens *for both arms*. Conditioning on `baseline_output_tokens` (a proxy for raw task difficulty) via rank-residual regression:

| agent | ρ(patch_lines, Δ_output) raw | ρ partial (\| baseline tokens) |
|---|---:|---:|
| claude | +0.228 | **+0.188** |
| codex | −0.134 | −0.012 |

For Claude, the patch-size correlation **survives** conditioning on baseline tokens (drops from 0.228 → 0.188, both positive). The signal is not purely a difficulty confound.

### Status of Pathway 1

**Holds qualitatively, with caveats.** Direction, slope gradient, cross-cell, cross-agent, median-split, and partial-correlation tests all agree. But effect sizes are modest:

- ρ ≈ 0.20–0.30 (small-to-moderate)
- R² of patch-size regressors on output tokens ≈ 0.01–0.05 (patch size explains only a small fraction of the variance)
- The aggregate Δ_output_tokens is +40%, but per-instance Spearman captures only part of it

So patch size is **one driver** of the onlycode penalty, not the only one.

---

## Pathway 2 — Difficulty confound (alternative)

**Alternative:** bigger patches = harder tasks. Harder tasks produce more output tokens for *every* arm (debugging chatter, more reasoning), and onlycode + baseline both scale with difficulty — but maybe onlycode's *scaling* is steeper for unrelated reasons (e.g., script-debug verbosity).

**Addressed by:**
1. Within-arm slope test: Claude baseline slope is ~7.5 tok/line, onlycode 26.9. If both were just "harder task → more output", slopes would be similar. They aren't.
2. Partial correlation (Test a'''): conditioning on baseline output tokens drops ρ from 0.228 to 0.188 — about 18% reduction. Most of the signal survives.
3. Codex doesn't show the same pattern. If the confound were "patch size = difficulty", Codex should also show output tokens scale with patch size in both arms. It doesn't (Codex slopes 4.4 vs 2.5, neither significant).

**Status:** Difficulty plays *some* role but doesn't dominate. The arm-specific scaling is the harder-to-explain-away signal.

---

## Pathway 3 — Verbosity (Claude's onlycode prompt elicits chattier reasoning)

**Alternative:** the onlycode regime's tool definition / system reminders / lack of `Edit` confirmation feedback might encourage Claude to write longer narration, longer code comments, longer planning paragraphs — independent of how many edits are needed.

**Evidence for:**
- The intercept of the within-arm OLS fit is +14,959 for onlycode vs +10,967 for baseline (Δ ≈ +4,000 tokens at zero patch size). Even on 0-line patches, onlycode would emit ~36% more tokens. **Most of the +40% marginal effect is in the intercept, not the slope.**
- Output tokens for low-patch (≤6 lines) instances: Δ = +2,650 (still highly significant). Even on tiny patches, onlycode pays a substantial fixed-cost tax.

**Evidence against:**
- The slope-difference test still excludes 0. So there's an *incremental* per-line tax on top of the fixed cost.
- Cross-cell: on Artifact tasks (where there's no edit but plenty of reasoning), Claude code_only does NOT pay an output-token tax (Δ = −605, NS). If verbosity were a pure regime effect, it should show up on Artifact too. It doesn't.

**Status:** verbosity probably explains a *fraction* of the gap (especially the intercept term). Edit friction explains the *additional slope* (the marginal penalty per gold-patch line). The two are complementary, not competing.

---

## Pathway 4 — Debug verbosity (failed scripts → diagnostic output)

**Alternative:** onlycode's Python scripts can crash, print stack traces, or require multiple iterations to get right. Each crash produces output (stderr captured by the harness, surfaced to the model). Bigger tasks = more code = more crashes = more debug chatter.

**Evidence for:**
- Δ_turns scales most strongly with patch size (ρ = +0.301 with files touched — the strongest single correlation we found). More turns means more iterations, which is what you'd see if the agent is debugging script failures.
- The slope gradient (baseline < bash_only < onlycode) also tracks how easy each medium is to debug — native Edit either applies cleanly or not, bash one-liners give quick feedback, full Python scripts can fail in many ways.

**Evidence against:**
- Can't test directly without inspecting transcripts. We'd need to parse JSONL logs to count "errored execute_code" calls.

**Status:** plausible co-mechanism with edit friction. Both predict that big patches need more code-writing AND more iterations. The current data can't disentangle them; both predict the same per-instance correlations.

---

---

## Reviewer-gap responses (post-opus review, 2026-05-28)

An opus-model subagent reviewed this writeup and the underlying scripts and raised six concerns. Follow-up scripts ran for each, with full results in [`edit_friction_v3.py`](edit_friction_v3.py).

### B1 — "Slope difference flips sign on the both-pass subset" (BLOCKING per reviewer)

**Reviewer's claim:** restricting to instances where both arms PASS (n = 37), OLS slope(onlycode) − slope(baseline) = **−11.3 tok/line**, i.e. onlycode is *less* steep on successful runs. The +19 tok/line effect is therefore mostly a *failure-debug-loop* effect, not an edit-verbosity effect per se.

**Reproduced — partially.** The verdict subsetting confirms the OLS pattern, but Theil-Sen (robust median slope) tells a different story:

| subset | n | OLS Δ slope | Theil-Sen Δ slope | mean output_tokens (base / only) |
|---|---:|---:|---:|---|
| ALL | 100 | +19.4 | **+62.4** | 11,138 / 15,578 |
| BOTH PASS | 37 | **−11.3** | **+22.1** | 5,530 / 8,593 |
| BOTH FAIL | 37 | +13.8 | **+63.1** | 14,047 / 20,809 |

The OLS-only flip is brittle: even on the both-pass subset, robust Theil-Sen shows a positive +22 tok/line edit tax (smaller than aggregate, but same sign). The +63 tok/line tax on the both-fail subset is *3× larger* than on both-pass — consistent with **two co-mechanisms**: a small fixed per-line tax (edit verbosity proper) plus a much larger debug-loop amplifier when scripts crash.

**Status:** the reviewer is right that failure-debug is a large component, but **wrong** that the both-pass slope difference disappears under a robust estimator. The headline mechanism (per-line edit tax) survives qualitatively on the both-pass subset. The honest framing is: **on successful runs, onlycode pays ~+22 tok/line; on failed runs, ~+63 tok/line — the gap is amplified by debug loops, not entirely caused by them.**

### B2 — "Codex `apply_patch` is only soft-disabled, so the Codex placebo is broken"

**Reviewer's claim:** [`paper/03_method.md:21`](../03_method.md#L21) confirms Codex `apply_patch` cannot be hard-disabled; it's discouraged via prompt prefix only. So Codex `onlycode` may still use it, and Codex `baseline` exposes a structured patch primitive — breaking the "no native Edit to lose" framing.

**Checked.** Parsed all 110 Codex onlycode JSONL logs in `runs/swebench/full_run_seed_1_codex_v2/`. Event-type counts by arm:

| arm | files | mcp_tool_call | command_exec | **file_change** | agent_msg |
|---|---:|---:|---:|---:|---:|
| baseline | 110 | 0 | 2,419 | **344** | 870 |
| onlycode | 110 | 1,731 | 58 | **4** | 929 |
| bash_only | 110 | 9 | 2,680 | **7** | 911 |

`file_change` events are how Codex's `apply_patch` mutations show up. Codex onlycode emits **4 file_change events across 110 instances** (concentrated in 1 instance: `scikit-learn-11596`). The soft-disable directive is followed >99% of the time. Codex baseline, by contrast, uses apply_patch heavily (344 file_changes).

**Status:** the placebo is **substantively intact**. The 4-event leak is too small to undermine the cross-agent comparison. The framing in this writeup is adjusted: Codex `baseline` does have a structured patch primitive, but Codex `onlycode` is empirically not using it.

### S1 — "OLS slope is leverage-dominated by the one 503-line outlier"

**Reviewer's claim:** the 503-line patch instance is ~5.7× the next largest. With R² ≈ 0.007, the OLS slope is fragile; dropping that one point should change the answer.

**Checked — and the leverage runs the opposite direction.** Leverage-drop sensitivity on Claude SWE-bench, all instances:

| drop top-N | n | max patch lines | OLS Δ slope | Theil-Sen Δ slope |
|---|---:|---:|---:|---:|
| 0 | 100 | 503 | +19.4 | +62.4 |
| 1 | 99 | 211 | **+68.6** | +70.7 |
| 3 | 97 | 89 | **+117.4** | +83.9 |
| 5 | 95 | 76 | **+82.2** | +76.1 |
| 10 | 90 | 63 | **+123.0** | +77.6 |

**Removing the 503-line point makes the slope difference *bigger*, not smaller.** That single instance was *suppressing* the apparent effect (it had +4,574 token Δ on a 503-line patch — far below the regression line). Theil-Sen is stable at +62–84 across all drop scenarios.

**Status:** the slope-difference result is **more robust than the original numbers suggested**, not less. The 95% CI [+3, +129] is wide *because* one influential point was anchoring it low.

### S2 — "Multiple-comparison correction not applied"

**Reviewer's claim:** 15 Spearman tests (5 metrics × 3 proxies) at α = 0.05 will yield false positives by chance.

**Done — BH @ FDR 0.05:**

Of 15 tests, **only `num_turns × patch_files_touched` (p_BH = 0.035) survives** strict BH correction. The output-token correlations narrowly miss (p_BH ≈ 0.078).

**Status:** the reviewer is right that the rank-correlation table is not BH-clean. **Concession:** the headline shouldn't lean on the Spearman table; lean on (i) the within-arm slope test (a *single* test that confirms +19 OLS / +62 Theil-Sen with CI excluding zero), (ii) the median-split contrast (one-sided MW p = 0.025), and (iii) the agent-actual edit-chars test (M3 below, p = 10⁻⁴). All three are individually robust.

### M3 — "Gold patch ≠ agent's actual patch"

**Reviewer's claim:** the agent's submitted patch can be very different in size from the gold patch. A direct test would use the agent's actual edit volume from JSONL logs.

**Done.** Parsed all 300 Claude SWE-bench logs (3 arms × 100 instances, seed 1). For each `tool_use` block, summed character counts of `Write.content`, `Edit.new_string`, `MultiEdit.edits[].new_string`, `execute_code.code`, and `Bash.command` — call this `edit_chars` (the amount the *agent* typed into mutation/action channels).

| arm | corr(edit_chars, output_tokens) | corr(edit_chars, gold_lines_added) |
|---|---:|---:|
| baseline | ρ = +0.829, p = 10⁻²⁶ | ρ = +0.432, p = 10⁻⁵ |
| onlycode | ρ = +0.839, p = 10⁻²⁷ | ρ = +0.398, p = 10⁻⁴ |
| bash_only | ρ = +0.880, p = 10⁻³³ | ρ = +0.349, p = 10⁻³ |

Within every arm, the more code/commands the agent issues, the more output tokens it produces — unsurprising, but it confirms that `edit_chars` is a meaningful measure of "agent's actual typing effort."

**The headline new test — paired Δ:**

| test | n | ρ | p |
|---|---:|---:|---:|
| Δ_edit_chars (onlycode − baseline) vs Δ_output_tokens | 100 | **+0.360** | **0.00024** |
| gold patch_lines_added vs Δ_output_tokens (the original a-test) | 100 | +0.228 | 0.023 |

**Per-instance, the *extra* characters Claude had to type under onlycode strongly track the *extra* output tokens it spent.** This correlation (ρ = +0.36, p < 0.001) is materially stronger than the gold-patch correlation (ρ = +0.23, p = 0.02). And it survives BH trivially — it's a single primary test.

**Status:** the agent-actual edit-chars test is now the cleanest single piece of evidence for the edit-friction mechanism. It's robust to "gold ≠ submitted patch" (M3), robust to multiple comparisons (S2 — one test), and orthogonal to the slope/leverage debate (S1).

### M2 — "Cross-cell control (artifact) confounds regime with task type" (MINOR)

**Conceded.** Artifact tasks differ from SWE-bench in many ways beyond "edit vs. write". The artifact result is *consistent with* edit friction being SWE-bench-specific but is not a clean isolation.

### M1 — "bash_only ordering claim oversold" (MINOR)

**Conceded.** The slope-gradient story (baseline 7.5 < bash_only 19.1 < onlycode 26.9 tok/line) is pattern-matching, not a tested ordering. Removed as load-bearing.

---

## What surprises remain

1. **Cost effect is non-significant in aggregate** (p = 0.21) despite the +40% output-token effect being p<10⁻⁹. Reason: output tokens are a small fraction of the total cost (input + cached tokens dominate). The cost is also more variable per-instance, so the test is underpowered. Per-instance Δ_cost ρ with patch size is +0.20 (p = 0.04) — directionally consistent but weaker.

2. **Codex `cost_usd` Δ has a marginally significant negative correlation** with patch size (ρ = −0.197, p = 0.049). I.e., bigger patches → onlycode *saves more* on cost vs baseline for Codex. Speculation: Codex tool_rich uses many small Edit-like tool calls (tool_calls = 25.7 vs onlycode 16.9, p<10⁻¹⁶); per-call overhead may compound with patch size, while onlycode's single-script approach is flat. Worth a sentence in the paper but not a paper-breaker.

3. **Claude bash_only − baseline shows positive slope (Δ slope = +11.6 tok/line) but no Spearman correlation on Δ.** Likely because bash_only's per-line tax is smaller than onlycode's, so the signal lives mostly in the tail (large-patch instances) which rank-based statistics down-weight relative to the bulk. Not contradictory; just lower statistical power.

4. **R² is very low (0.001–0.012).** Patch size is a weak predictor of absolute output tokens in any one arm — task variance dominates. But it's enough to *differentiate* arm slopes, which is the test that actually matters here.

---

## Bottom line (post-review)

**Edit friction is supported as a contributing mechanism** for Claude's SWE-bench `onlycode` cost / output-token tax. The hypothesis survived all six gap-checks the opus reviewer raised, although three of them required reframing what the strongest evidence is. Refined picture:

1. **Strongest single test (M3):** per-instance Δ_edit_chars (onlycode − baseline) — the *extra* characters Claude actually types under onlycode — correlates with Δ_output_tokens at **ρ = +0.36, p = 2×10⁻⁴**. This is one test (no multiple-comparison concern), uses agent-actual rather than gold patches, and is independent of the OLS-slope/leverage debate.
2. **Robust slope test (B1+S1):** the Theil-Sen median slope of output_tokens on patch_lines_added is **+62 tok/line higher for onlycode than baseline** on the full set. On the both-PASS subset alone (n=37) the gap is **+22 tok/line**. On the both-FAIL subset (n=37) it's **+63 tok/line** — debug loops amplify but do not cause the effect.
3. **Fixed-cost component is large:** intercept gap ≈ +4,000 tokens at zero patch size. Even on tiny patches, onlycode pays a regime-level verbosity tax. The +40% aggregate Δ_output_tokens is *partly* this intercept and *partly* the per-line edit tax.
4. **Cross-agent placebo (B2):** Codex's `apply_patch` soft-disable is empirically respected — Codex onlycode logs show 4 file_change events across 110 instances vs 344 in baseline. The Codex placebo (no slope difference) therefore tests what it's meant to test.
5. **Multiple-comparison caveat (S2):** the 15-cell Spearman table is *not* BH-clean; only `num_turns × files_touched` survives FDR 0.05. The headline should *not* lean on the rank-correlation table — it should lean on the three orthogonal robust tests above (M3, Theil-Sen slope, median split).

**Paper-figure recommendation (revised):** a 2-panel figure. Left panel: **scatter of Δ_output_tokens vs Δ_edit_chars across the 100 Claude SWE-bench instances, with the +0.36 Spearman ρ called out**. Right panel: **median-split bar chart showing onlycode−baseline Δ_output_tokens on the low-patch half (+2,650) vs the high-patch half (+6,378), with the 2.4× ratio called out**. This is more honest than the per-arm OLS-line figure, which would lean on R² < 0.01 fits.

**Numerical headline (revised):** "**On instances where Claude must type substantially more code under `onlycode` than under `baseline`, it also spends substantially more output tokens — Spearman ρ = +0.36 (p < 10⁻³, n = 100). The output-token tax is 2.4× larger on the high-patch half of the instance set (p = 0.025).** Approximately +4,000 tokens of the aggregate +40% gap is regime-level verbosity (intercept); the remainder scales with edit volume."

**Outstanding caveats:**
- Edit-friction is one mechanism, not the only one. Fixed-cost verbosity (intercept) and failure-debug verbosity (amplifies on both-fail subset) both contribute substantially.
- All numbers come from seed 1 of `full_run_seed_1` (Claude) and `full_run_seed_1_codex_v2` (Codex). Seeds 2/3 should be re-run before pulling any of these numbers into the paper.
- The Codex placebo is *not perfect* — 4 apply_patch leaks remain. Reviewers may ask.
- Distinguishing "edit verbosity" from "debug-iteration verbosity" cleanly would require a separate analysis counting non-zero-exit `execute_code` calls. Not done here; flagged for follow-up.

**Where I downweight my own prior writeup:**
- The "3.6× slope ratio" headline was overweighting OLS on a low-R² fit. The Theil-Sen / leverage-drop analysis actually shows the slope-ratio is *larger* than 3.6× when the influential 503-line point is removed — but the cleanest way to state the result is the M3 correlation, not a slope ratio.
- The cross-cell artifact argument is hand-wavy. It's consistent with the hypothesis but doesn't isolate edit-vs-no-edit.
- The bash_only "ordering" gradient is suggestive but not load-bearing.
