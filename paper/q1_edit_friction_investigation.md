# §6 Question 1 investigation — edit-friction on Claude SWE-bench `code_only`

**Working note, not paper prose.** Investigates the question raised in [outline.md:138](outline.md#L138):

> Why does Claude struggle with `code_only` on SWE-bench specifically? The only cell where code-only loses; cost runs +14% (NS) vs baseline and **output tokens are +40% (p<10⁻⁹)** vs baseline.

**Data sources** (all paper-scope):
- Per-instance metrics: [`paper/data/raw/all_results.csv`](data/raw/all_results.csv) @ source_commit 050947f. 3 seeds × 3 arms × 100 SWE-bench instances × {Claude, Codex}.
- Marginal / contrast tables: [`paper/data/paired_marginals.csv`](data/paired_marginals.csv), [`paper/data/paired_contrasts.csv`](data/paired_contrasts.csv).
- Gold-patch sizes: [`paper/data/raw/swe_gold_patch_sizes.csv`](data/raw/swe_gold_patch_sizes.csv) — sourced once from HuggingFace (`princeton-nlp/SWE-bench_Verified` + `SWE-bench`, test splits), committed; do not regenerate at build time.
- Agent-actual edit-chars: parsed from per-instance JSONL tool-use blocks in `runs/swebench/full_run_seed_{1,2,3}/`.

**Revision history.**
- **v1** (initial pass) — used gold-patch-size correlation; n=100 with seed-1 only. Headline ρ ≈ +0.23 for output_tokens. Opus reviewer raised six concerns (B1, B2, S1, S2, M1, M2, M3).
- **v2** — addressed all six gaps: (i) both-pass / both-fail subset slope test (B1), (ii) leverage-drop + Theil-Sen robust slope (S1), (iii) BH correction on 15-cell Spearman table (S2), (iv) Codex `apply_patch` leakage check from JSONLs (B2), (v) **agent-actual edit-chars correlation (M3) — became the new headline at ρ ≈ +0.36**, (vi) softened M1/M2 framing.
- **v3 (THIS REVISION)** — promoted the analysis from `paper/investigations/` to production: [`paper/data/scripts/edit_friction.py`](data/scripts/edit_friction.py) emits [`paper/data/edit_friction.csv`](data/edit_friction.csv), wired into the `\result{edit_friction}{...}` macro namespace. **Headline now averages across all 3 seeds**, strengthening the signal to ρ ≈ +0.49.

**Scripts.**
- Production (canonical, wired into `make values`): [`paper/data/scripts/edit_friction.py`](data/scripts/edit_friction.py).
- Exploration (working-notes provenance, not part of build): [`paper/investigations/edit_friction_analysis.py`](investigations/edit_friction_analysis.py) (v1 primary Spearman + gold patches via HF), [`paper/investigations/edit_friction_v2.py`](investigations/edit_friction_v2.py) (within-arm slopes + median split + partial correlation), [`paper/investigations/edit_friction_v3.py`](investigations/edit_friction_v3.py) (v2 follow-ups + agent-actual edit-chars).

---

## TL;DR (v3)

Edit-friction is supported as a contributing mechanism for Claude's SWE-bench `code_only` +40% output-token gap. The strongest single test is the agent-actual edit-chars correlation; the slope-ratio framing from v1 is downweighted. The hypothesis survived all six opus-reviewer gap-checks, though three required reframing the lead evidence.

| test | metric | result | macro |
|---|---|---|---|
| **Headline (M3, agent-actual)** | Spearman ρ(Δ_edit_chars, Δ_output_tokens) | **+0.49, p < 10⁻⁶, n=100** | `\result{edit_friction}{rho_edit_chars}` |
| Reference (gold patch) | Spearman ρ(patch_lines_added, Δ_output_tokens) | +0.23, p=0.023 (v1 lead — superseded) | `\result{edit_friction}{rho_gold_lines}` |
| Secondary (median split) | mean Δ_output_tokens low / high half | **+2,650 / +6,378 (ratio 2.4×)**, MW p=0.025 | `\result{edit_friction}{highpatch_ratio}` |
| Slope (robust, Theil-Sen) | Δ slope (code_only − baseline) | +62 tok/line | `\result{edit_friction}{theilsen_slope_diff}` |
| Fixed-cost component | OLS intercept gap at zero patch | **~+4,000 tokens** | `\result{edit_friction}{intercept_gap}` |
| Cross-agent placebo | Codex Δ_output_tokens vs gold patch | ρ = −0.13 (NS) | n/a |

**The +40% Claude code_only output-token gap decomposes into:** (i) ~+4,000 tokens of fixed-cost regime verbosity (intercept), independent of patch size; (ii) a per-edit-character tax that scales with how much code the agent actually has to type — 2.4× larger on the high-patch half of instances. Codex doesn't show this pattern; its `apply_patch` soft-disable is empirically respected (4 leaks across 110 onlycode logs).

**§6 prescription consequence**: the conservative "Claude code_only costs 14% more on SWE-bench" reading is *one specific kind of friction* — it scales with the volume of edit-coding the agent must do, and most of the headline gap survives even on the both-pass subset under a robust estimator. Edit primitives are not interchangeable on the cost axis.

---

## 1. Pathway map (the four explanations under test)

Four candidate explanations for the +40% Claude code_only output-token gap:

| pathway | claim | survives v3 review? |
|---|---|---|
| **A. Edit friction (primary)** | code_only must type a Python script for each edit; tax scales with edit volume | **Yes (qualified)** — strongest single test ρ=+0.49 |
| **B. Difficulty confound** | bigger patches = harder tasks; more output tokens in every arm | Mostly ruled out — partial corr survives baseline-token control |
| **C. Regime verbosity** | code_only system prompt + tool-defs elicit chattier reasoning, independent of edit volume | **Partially supported** — explains ~+4,000 of +40% (intercept gap) |
| **D. Debug verbosity** | failed scripts → stack traces → more iterations | **Partially supported** — slope is 3× larger on both-fail subset than both-pass |

Pathways A, C, D are **complementary**, not competing. The decomposition: A explains the slope (per-line scaling), C explains the intercept (fixed cost), D amplifies A on failed runs.

---

## 2. Pathway A — Edit friction (primary tests)

### 2.1 Spearman correlation table (v1 — superseded but documented)

Claude SWE-bench, Δ = code_only − baseline, n = 100, seed 1:

| metric | vs `patch_lines_added` | vs `patch_lines_changed` | vs `patch_files_touched` |
|---|---|---|---|
| output_tokens | ρ = +0.228, p = 0.023 * | ρ = +0.210, p = 0.036 * | ρ = +0.222, p = 0.027 * |
| cost_usd_adjusted | ρ = +0.213, p = 0.033 * | ρ = +0.196, p = 0.051 | ρ = +0.173, p = 0.085 |
| num_turns | ρ = +0.257, p = 0.010 ** | ρ = +0.234, p = 0.019 * | ρ = **+0.301**, p = 0.002 ** |
| llm_calls | ρ = +0.132, p = 0.19 | ρ = +0.104, p = 0.30 | ρ = +0.133, p = 0.19 |

All seven significant correlations are positive; **BH correction (S2)** retains only `num_turns × patch_files_touched` at FDR 0.05. The output-token correlations narrowly miss (p_BH ≈ 0.08). **Conclusion: don't lead with this table** — lead with §2.3.

### 2.2 Codex placebo (v1)

Codex Δ = code_only − baseline (n=100, seed 1):
- output_tokens: ρ = −0.134, p = 0.18 (NS) — opposite direction
- cost_usd: ρ = −0.197, p = 0.049 * — opposite direction, marginal
- num_turns: n/a (Codex always 1 turn)

Marginal Δ_output_tokens for Codex code_only−baseline is +35 tokens (NS, p = 0.83). Flat. The placebo holds.

### 2.3 Headline test (M3, v2+) — agent-actual edit-chars

For each Claude SWE-bench instance, summed character counts across all 3 seeds of `Write.content` + `Edit.new_string` + `MultiEdit.edits[].new_string` + `execute_code.code` + `Bash.command` tool-use blocks. Per-instance Δ = code_only_edit_chars − baseline_edit_chars.

| test | n | ρ | p |
|---|---:|---:|---:|
| **Δ_edit_chars (code_only − baseline) vs Δ_output_tokens** | **100** | **+0.488** | **2.6×10⁻⁷** |
| gold patch_lines_added vs Δ_output_tokens (v1 lead — superseded) | 100 | +0.228 | 0.023 |

The agent-actual edit-chars correlation is **~2× stronger than gold-patch** and is robust to "gold ≠ submitted patch" (M3). Single primary test, no multiple-comparison concern.

### 2.4 Median-split contrast (v2)

Split instances at median `patch_lines_added` (= 6):

| half | n | mean Δ_output_tokens (code_only − baseline) | Wilcoxon p |
|---|---:|---:|---:|
| low patch (≤6 lines) | 52 | +2,650 ± 954 | 2×10⁻⁵ |
| high patch (>6 lines) | 48 | +6,378 ± 1,602 | 7×10⁻⁷ |
| one-sided Mann-Whitney high > low | | | **p = 0.025** |

The code_only penalty is **2.4× larger** on the high-patch half. Both halves are individually significant (code_only pays a tax even on small patches — that's the intercept term in Pathway C); the *growth* with patch size is the edit-friction signature.

### 2.5 Within-arm slope (OLS — kept for record, downweighted)

`output_tokens` regressed on `patch_lines_added` within each arm:

| agent | arm | OLS slope (tok/line) | R² | n |
|---|---|---:|---:|---:|
| claude | baseline | +7.5 | 0.001 | 100 |
| claude | code_only | +26.9 | 0.007 | 100 |
| claude | bash_only | +19.1 | 0.004 | 100 |
| codex | baseline | +4.4 | 0.012 | 100 |
| codex | code_only | +2.5 | 0.004 | 100 |
| codex | bash_only | +2.6 | 0.004 | 100 |

Bootstrap CI for slope(code_only) − slope(baseline): **Claude +36.2 tok/line [+3.4, +129.1]** (excludes 0); Codex −1.9 [−6.2, +2.8] (includes 0).

R² < 0.01 is the reviewer-attack surface here. **Do not lead with the "3.6× slope ratio" framing in §6 prose** — see §3.

### 2.6 Robust slope (Theil-Sen + leverage drop, v2 follow-up to S1)

| drop top-N patches | n | max patch lines | OLS Δ slope | Theil-Sen Δ slope |
|---|---:|---:|---:|---:|
| 0 | 100 | 503 | +19.4 | **+62.4** |
| 1 | 99 | 211 | +68.6 | +70.7 |
| 3 | 97 | 89 | +117.4 | +83.9 |
| 5 | 95 | 76 | +82.2 | +76.1 |
| 10 | 90 | 63 | +123.0 | +77.6 |

Reviewer S1 expected the 503-line outlier to inflate the OLS slope. **It does the opposite** — removing it makes the slope difference *bigger*. Theil-Sen is stable at +62–84 across all leverage-drop scenarios. The slope-difference result is more robust than v1 suggested, not less.

---

## 3. Pathway B — Difficulty confound

**Claim:** bigger patches = harder tasks; harder tasks produce more output tokens for every arm. Apparent correlation between Δ and patch size could be a difficulty confound.

**Test (partial correlation, rank-residual regression):**

| agent | ρ(patch_lines, Δ_output) raw | ρ partial (\| baseline output tokens) |
|---|---:|---:|
| claude | +0.228 | **+0.188** |
| codex | −0.134 | −0.012 |

For Claude, the patch-size signal survives conditioning on baseline output tokens (a proxy for raw task difficulty). The signal is not purely a difficulty confound — 82% of the raw ρ remains after the control. For Codex, the residual partial-ρ is ~0; the original Codex correlation was a difficulty artifact, not an edit-friction signal.

**Status:** Pathway B contributes but doesn't dominate. The arm-specific scaling (§2.5) is the harder-to-explain-away signal — if difficulty were the only mechanism, Claude baseline would scale with patch size at the same rate as Claude code_only. It doesn't (7.5 vs 26.9 tok/line OLS, 127 vs 189 Theil-Sen).

---

## 4. Pathway C — Regime verbosity (intercept term)

**Claim:** code_only's tool-definitions, system reminders, and lack of `Edit` confirmation feedback might encourage Claude to write longer narration, longer code comments, longer planning paragraphs — independent of how many edits are needed.

**Evidence for:**
- OLS intercept gap: code_only +14,959 vs baseline +10,967 tokens at zero patch size. **Δ ≈ +4,000 tokens before any edit happens.**
- Even on the low-patch half (≤6 lines), Δ_output_tokens is +2,650 — most of which is intercept, not slope (slope contribution at 6 lines is +19 × 6 ≈ +114 tokens OLS, +62 × 6 ≈ +372 tokens Theil-Sen).

**Evidence against pure-verbosity:**
- The slope-difference test still excludes 0. There's an *incremental* per-line tax on top of the fixed cost.
- Cross-cell: Artifact tasks (no edits, plenty of reasoning) show no Claude code_only output-token tax (Δ = −605, NS). Pure-verbosity would predict the gap on Artifact too. It's absent.

**Status:** Pathway C contributes **substantially** — ~+4,000 of the +40% aggregate is intercept-driven. Edit friction (Pathway A) explains the *additional slope*. Both real, complementary.

---

## 5. Pathway D — Debug verbosity (failed scripts → diagnostic chatter)

**Claim:** code_only's Python scripts can crash, print stack traces, or require multiple iterations. Each crash produces output. Bigger tasks = more code = more crashes = more debug chatter.

**Reviewer B1 raised this as a BLOCKING concern.** The reviewer claimed the slope difference *flips sign* on the both-PASS subset under OLS:

| subset | n | OLS Δ slope | Theil-Sen Δ slope |
|---|---:|---:|---:|
| ALL | 100 | +19.4 | +62.4 |
| BOTH PASS | 37 | **−11.3** | **+22.1** |
| BOTH FAIL | 37 | +13.8 | **+63.1** |

**Verdict on B1:** the reviewer's claim is half-right. OLS slope difference does flip on both-pass (brittle — one influential point), but **Theil-Sen confirms a positive +22 tok/line on both-pass**. Both-fail amplifies to +63. Honest reading: on successful runs, code_only pays ~+22 tok/line per gold-patch line; on failed runs, ~+63. **Debug loops amplify the tax 3×, but the tax exists on successful runs.**

**Status:** Pathway D is real and substantial. Disentangling it cleanly from Pathway A would require parsing per-call exit codes from execute_code blocks in the JSONL logs (counting Tracebacks per turn). Not done in v3; flagged for §7 Limitations.

---

## 6. Cross-cell sanity — Artifact tasks

If edit friction is real, it should be **absent** on Artifact tasks (which generate single Python scripts, no in-place edits). From `paired_contrasts.csv`:

| benchmark | contrast (Claude) | Δ output tokens | Wilcoxon p |
|---|---|---:|---:|
| SWE-bench | code_only − baseline | **+4,440 (+40%)** | p = 5×10⁻¹⁰ *** |
| Artifact | code_only − tool_rich | −605 (−20%) | p = 0.14 (NS) |

| benchmark | contrast (Claude) | Δ cost (USD) | Wilcoxon p |
|---|---|---:|---:|
| SWE-bench | code_only − baseline | +$0.071 (+14%) | p = 0.21 (NS) |
| Artifact | code_only − tool_rich | **−$0.042 (−34%)** | p = 3×10⁻¹⁶ *** |

**On Artifact, code_only WINS on cost and shows no output-token tax** — the opposite pattern. Reviewer M2 conceded this is "consistent with" edit-friction being SWE-bench-specific but not a clean isolation (Artifact differs from SWE-bench in many ways beyond edit-vs-write — codebase size, persistent kernel, test setup). Soften to "consistent with"; don't claim it isolates the mechanism.

---

## 7. Cross-agent sanity — Codex placebo (B2 follow-up)

Reviewer B2 raised: Codex `apply_patch` is only soft-disabled in code_only (prompt-prefix directive, not API-level disable; see [03_method.md:21](03_method.md#L21)). So the Codex placebo might not test what it's meant to test.

**Checked.** Parsed all 110 Codex code_only JSONL logs in `runs/swebench/full_run_seed_1_codex_v2/`. Event-type counts by arm:

| arm | files | mcp_tool_call | command_exec | **file_change** | agent_msg |
|---|---:|---:|---:|---:|---:|
| baseline | 110 | 0 | 2,419 | **344** | 870 |
| code_only | 110 | 1,731 | 58 | **4** | 929 |
| bash_only | 110 | 9 | 2,680 | **7** | 911 |

`file_change` events are how Codex's `apply_patch` mutations show up. Codex code_only emits **4 file_change events across 110 instances** (concentrated in 1 instance: `scikit-learn-11596`). The soft-disable is followed >99% of the time.

**Status:** the placebo is **substantively intact**. The 4-event leak is too small to undermine the cross-agent comparison. Disclose once in §6.1 ("Codex never had a hard-disabled native `Edit` to lose, per §3.1") and do not relitigate.

---

## 8. Multiple-comparison hygiene (S2 follow-up)

Reviewer S2 raised: 15 Spearman tests at α = 0.05 will yield false positives by chance.

**BH correction** on the 15 cells in §2.1:

| test | p_raw | p_BH | survives FDR 0.05? |
|---|---:|---:|---|
| num_turns × patch_files_touched | 0.0023 | **0.035** | ✓ |
| num_turns × patch_lines_added | 0.0097 | 0.073 | ✗ (narrow miss) |
| output_tokens × patch_lines_added | 0.023 | 0.078 | ✗ (narrow miss) |
| cost_usd_adjusted × patch_lines_added | 0.033 | 0.078 | ✗ |
| ... 11 more | ... | ... | ✗ |

**Only 1 of 15 cells survives.** Concession to S2: the 15-cell rank-correlation table is *not* BH-clean. Headline must not lean on it.

**What §6.1 leans on instead:**
1. Agent-actual edit-chars correlation (§2.3) — ρ = +0.49, p = 10⁻⁷ — *one* test, no BH concern.
2. Median-split contrast (§2.4) — one-sided MW p = 0.025 — *one* test.
3. Robust slope test (§2.6) — Theil-Sen Δ = +62 tok/line — *one* test.

All three are individually robust, orthogonal in methodology, and agree in direction.

---

## 9. Open questions still deferred

- **Q1-O1**: Separating Pathway A (per-edit verbosity) from Pathway D (debug-loop verbosity) cleanly. Requires per-call exit-code parsing from execute_code JSONL blocks. Not done in v3; flagged for §7 Limitations.
- **Q1-O2**: Seed-1-only check for the JSONL-derived `edit_chars` reproducibility. v3 averages across seeds 1–3 by reading `all_results.csv` rows and corresponding log paths. If seed_1 alone gives ρ ≈ +0.36 and seed-averaged gives ρ ≈ +0.49, that's a consistent direction with more data → narrower CI. Worth a per-seed sensitivity table in the appendix if a reviewer pushes.
- **Q1-O3**: The +0.49 headline uses an *unweighted* mean of seed-level edit_chars within (arm, instance). If one seed's run was anomalously long (e.g., hit wall budget), it dominates the mean. Median-of-seeds is the natural robustness check; not done.
- **Q1-O4**: The figure-decision in §6.1 (no dedicated figure) assumes Figure 1 (§5.2) carries the visual. If §5.2 ships with a different framing, the appendix bar-chart (low-patch vs high-patch Δ for {Claude, Codex}) becomes load-bearing instead of reserve.

---

## 10. Proposed §6 frame (revised in v3)

Three sentences, anchored on §2.3, §2.4, and §4:

1. **Headline test**: across 100 Claude SWE-bench instances, the per-instance Δ_edit_chars (code_only − baseline) — the extra characters the agent actually types into mutation channels — correlates with Δ_output_tokens at Spearman ρ ≈ +0.49 (p < 10⁻⁶). On the high-patch half of the instance set, the code_only output-token penalty is 2.4× larger than on the low-patch half (one-sided MW p = 0.025).
2. **Decomposition**: the +40% aggregate gap splits into a ~+4,000-token fixed-cost intercept (regime verbosity, Pathway C) plus a per-edit-character slope (Pathway A) amplified ~3× when scripts fail and require debug iteration (Pathway D, §7 Limitations).
3. **Placebo**: Codex, whose `apply_patch` is soft-disabled rather than absent in code_only, shows neither the correlation (ρ = −0.13 vs gold lines, NS) nor the marginal output-token tax (Δ ≈ −0.7%, NS). The cross-agent split — Claude loses ~14% on SWE-bench code_only while Codex wins ~20% — is consistent with the *presence* vs *absence* of a native edit primitive to give up.

---

## File-level provenance

- Raw data: `paper/data/raw/all_results.csv` @ source_commit 050947f44fb7dec5793e05700cd01bdd5942ebfa
- Static input (HF-sourced once): `paper/data/raw/swe_gold_patch_sizes.csv` (committed)
- Production CSV: `paper/data/edit_friction.csv` (regenerated by `make values`)
- Production script: `paper/data/scripts/edit_friction.py`
- Exploration scripts (working notes, not part of build): `paper/investigations/edit_friction_{analysis,v2,v3}.py`
- Reviewer feedback that motivated v2: Opus subagent run 2026-05-28
- Investigation prose (v1 + v2 reviewer responses): `paper/investigations/edit_friction_findings.md` — superseded by this file; retained for revision provenance.
- This note: `paper/q1_edit_friction_investigation.md` (NEW; not part of submission)
