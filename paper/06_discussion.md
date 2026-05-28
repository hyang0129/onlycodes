# 06 — Discussion
# THIS IS A MORE DETAILED OUTLINE NOT THE ACTUAL PAPER DRAFT

**Role of this file.** Per-section outline. Compiled prose lives in `sections/06_discussion.tex`; this file plans the structure and pinned content. The discussion has one job: take the §5 four-cell cost structure (and especially the asymmetric SWE-bench/Claude cell where `code_only` is the only one not winning), explain *why* it lands the way it does, and hand the reader something actionable. It is **not** a re-statement of §5 results in prose; it is the mechanism layer that the headline numbers leave unexplained.

**Page target:** 0.5 page (ceiling 0.75), per [outline.md:22](outline.md#L22) (budget table) and [outline.md:140](outline.md#L140) (section header). The 8-page workshop ceiling is binding; if §5 overruns, the first place §6 gives up budget is §6.4–§6.6, not the three mechanism questions.

**Drafting rule.** Every numeric claim in compiled prose comes through `\result{...}` (or `\resdelta`/`\resratio`) macros backed by CSVs in `paper/data/`. No bare digits. `paper/lint.py` enforces this. **§5 numbers freeze ✅ cleared 2026-05-28** — §6.1 and §6.5 can proceed against existing CSVs (`paired_contrasts.csv`, `edit_friction.csv`); §6.3 and the §6.6 prescriptions remain gated on `agreement_matrix.csv` / `headline_unanimous.csv`; §6.2 is gated on `mcp_output_size.csv`.

## Structure (6 subsections)

### 6.1 Mechanism Q1 — Why Claude's `code_only` loses on SWE-bench (~100 words / ~0.18 page)

The only cell in Table 1 where `code_only` spends more than its closest rival. Cost runs +14% (NS) vs `baseline`; output tokens are +40% (highly significant). **Working hypothesis: edit friction** — `code_only` must express each file edit as a Python script rather than as one native `Edit`/`Write` call.

**Lead with:** per-instance Δ_edit_chars (`code_only` − `baseline`) vs Δ_output_tokens — Spearman **`\result{edit_friction}{rho_edit_chars}`** (`p ≈ \result{edit_friction}{rho_edit_chars_p}`, n=100). Edit-chars come from JSONL tool-use blocks (Write/Edit/MultiEdit/execute_code/Bash content). One primary test, no multiple-comparison concern.

**Secondary:** median-split — Δ_output_tokens of **`\result{edit_friction}{lowpatch_delta_output_tokens}`** on the low-patch half vs **`\result{edit_friction}{highpatch_delta_output_tokens}`** on the high-patch half (Mann-Whitney p = `\result{edit_friction}{highpatch_mw_p}`); the per-instance penalty scales with edit volume, not constant.

**Placebo:** Codex `code_only`-vs-`baseline` output-tokens Δ ≈ −0.7% (NS). Codex never had a hard-disabled native `Edit` to lose (per §3.1). Back-reference §3.1, do not relitigate.

**Caveat to surface in-paragraph:** ~`\result{edit_friction}{intercept_gap}` of the +40% aggregate gap is fixed-cost regime verbosity (intercept at zero patch size). Edit friction is the *additional* per-line tax, not the whole gap.

**Cross-question note (one sentence in compiled prose):** the +17% LLM-call inflation documented in §6.2 for this same cell is consistent with the per-line edit tax — more Python composition per edit means more rounds; the two analyses converge on one mechanism viewed at different granularities. §6.3 further confirms edit-friction is a **path-cost** (Δoutput tok stays at +44% on the unanimous-pass subset where the failure-cost component is removed) — it is one of two mechanisms cohabiting this cell, the other being the §6.3 failure-cost on doomed runs.

**Numbers:** [`paper/data/edit_friction.csv`](data/edit_friction.csv), produced by [`paper/data/scripts/edit_friction.py`](data/scripts/edit_friction.py). Static input: [`paper/data/raw/swe_gold_patch_sizes.csv`](data/raw/swe_gold_patch_sizes.csv).

**Investigation note:** [`paper/q1_edit_friction_investigation.md`](q1_edit_friction_investigation.md) — full v1→v3 evolution including opus-reviewer gap responses and the four pathway decomposition (A edit-friction, B difficulty-confound, C regime-verbosity, D debug-verbosity). See §10 of that file for the canonical three-sentence §6 frame.

**Figure decision:** *no dedicated figure*. Figure 1 (§5.2) already shows Claude SWE-bench `code_only` right-tail losses, providing visual motivation. Reserved appendix figure (if reviewers push): 4-bar median-split chart of Δ_output_tokens for {Claude, Codex} × {low-patch, high-patch}.

### 6.2 Mechanism Q2 — Why `code_only` shifts the per-LLM-call input budget (~100 words / ~0.18 page)

On SWE-bench Codex, LLM-call counts are flat across arms (~18 each), yet `code_only` uses ~25% fewer input tokens and ~25% fewer tool calls than `baseline`. The originally hypothesized "MCP output compression" framing is **falsified** — the median per-call output is actually *larger* under `execute_code` than under `exec_command` in every cell we measured. Two cleaner mechanisms drive the win:

- **(H1) Tool-call batching.** At nearly identical LLM-round counts (`\result{mcp_output_size}{codex_swebench:baseline:llm_calls_per_run}` for `baseline` vs `\result{mcp_output_size}{codex_swebench:onlycode:llm_calls_per_run}` for `onlycode`), `execute_code` issues `\result{mcp_output_size}{codex_swebench:onlycode:calls_per_run}` tool calls per run vs `\result{mcp_output_size}{codex_swebench:baseline:calls_per_run}` for `baseline` — one Python script subsumes what `exec_command` requires several calls to do. The per-turn metric `tools_per_llm` is not the right test: `baseline` registers higher there because it has *two* tools available (`exec_command` + `apply_patch`) and fires them in parallel within a turn, which is a different phenomenon than the within-script batching H1 names.
- **(H2) Upper-tail suppression.** Median per-call output is unchanged (`\result{mcp_output_size}{codex_swebench:onlycode:median_chars}` vs `\result{mcp_output_size}{codex_swebench:baseline:median_chars}` chars), but p99 collapses from `\result{mcp_output_size}{codex_swebench:baseline:p99_chars}` (the `exec_command` `max_output_tokens` ceiling) to `\result{mcp_output_size}{codex_swebench:onlycode:p99_chars}` — the agent paginates output in Python rather than dumping verbatim stdout.

The `bash_only` control reproduces neither signal, ruling out "restrict native tools" as the active ingredient.

**Cross-cell scope.** H1 holds for Codex on both benchmarks; Claude empirically does not batch on either benchmark — on Claude SWE-bench `onlycode` issues *more* tool calls per run than `baseline` (`\result{mcp_output_size}{claude_swebench:onlycode:calls_per_run}` vs `\result{mcp_output_size}{claude_swebench:baseline:calls_per_run}`), and the Claude Artifact reduction tracks a parallel drop in LLM rounds rather than per-step batching. H2 holds in 3 of 4 cells; the exception is Codex Artifact, where the rival surface already produces tight outputs and there is no tail to suppress.

**Triangulation with §6.1.** On Claude SWE-bench, H2 still holds at the per-call level (p99 drops from `\result{mcp_output_size}{claude_swebench:baseline:p99_chars}` to `\result{mcp_output_size}{claude_swebench:onlycode:p99_chars}`) but `onlycode` *loses* on input tokens because LLM-call count inflates by ~17%. The same cell §6.1 explains as edit-friction is the cell §6.2 sees as round-count inflation — two angles on one mechanism.

**Test:** [`paper/data/scripts/mcp_output_size.py`](data/scripts/mcp_output_size.py) → [`paper/data/mcp_output_size.csv`](data/mcp_output_size.csv) (to be written; mirrors `edit_friction.py` structure). Full investigation: [`paper/q2_token_gap_investigation.md`](q2_token_gap_investigation.md).

### 6.3 Mechanism Q3 — Why pass rates are statistically tied across arms despite 20–40% cost swings (~120 words / ~0.20 page)

Pass rates differ by <3pp across all 4 cells × 3 arms (all NS), yet costs differ by 20–40% with overwhelming significance.

**Frame:** tool restriction is a *harness-efficiency* axis orthogonal to *model capability* — the model solves the task with any reasonable interface; the surface changes the path, not the answer.

**Anchored on §5.4.** Unanimous-outcome instances dominate every cell: **`\result{agreement_matrix}{artifact:claude:unanimous_majority_pct}` / `\result{agreement_matrix}{artifact:codex:unanimous_majority_pct}` / `\result{agreement_matrix}{swebench:claude:unanimous_majority_pct}` / `\result{agreement_matrix}{swebench:codex:unanimous_majority_pct}`** under majority-vote (per arm pass-rate ≥ 2/3); ≥`\result{agreement_matrix}{_all:_all:min_unanimous_strict_pct}` under the strictest 9/9-trials criterion. Splits are graded-difficulty mixes (not arm-specific easy-subsets): only `\result{agreement_matrix}{swebench:claude:strictly_arm_specific_split_n}` / `\result{agreement_matrix}{swebench:claude:split_majority_n}` split instances on Claude SWE-bench have a single arm carrying all the passes. The dissociation thesis holds.

**Localization: Claude SWE-bench is the one anomaly cell.** In 3 of 4 cells `code_only` is the cheaper arm by a large and significant margin (Artifact Claude `\result{headline}{artifact_claude_cost_adj_pct}`, Artifact Codex `\result{headline}{artifact_codex_cost_adj_pct}`, SWE-bench Codex `\result{headline}{swebench_codex_cost_adj_pct}`). The lone exception is **Claude SWE-bench** (`\result{headline}{swebench_claude_cost_adj_pct}`, NS) — the cell §6.3 has to explain. The other three need no special accounting under the path-not-answer thesis.

**Two-mechanism decomposition on Claude SWE-bench (v3 finding).** When we re-run the headline-style cost pipeline restricted to the unanimous-pass subset (cache floor recomputed on the subset), the contrast metrics split cleanly: **`onlycode`'s Δcost adj. collapses from `\result{headline_unanimous}{swebench:claude:onlycode-vs-baseline:cost_adj:full_mean_delta_pct}` (NS) to `\result{headline_unanimous}{swebench:claude:onlycode-vs-baseline:cost_adj:unanimous_majority_mean_delta_pct}` (NS)** and Δinput tok flips from significant (`\result{headline_unanimous}{swebench:claude:onlycode-vs-baseline:input_tokens:full_mean_delta_pct}`, p<0.05) to NS (`\result{headline_unanimous}{swebench:claude:onlycode-vs-baseline:input_tokens:unanimous_majority_mean_delta_pct}`), while **Δoutput tok stays at `\result{headline_unanimous}{swebench:claude:onlycode-vs-baseline:output_tokens:unanimous_majority_mean_delta_pct}` (still highly significant)**. The split has a clean reading: the input-side blowup is *failure-cost* (extended failed-run trajectories under `bash`/`onlycode`), while the output-side blowup is the *edit-friction path-cost* §6.1 identifies — two mechanisms cohabiting one cell, separated by conditioning on success.

**Cross-question note (one sentence in compiled prose):** §6.1's edit-friction is the path-cost component of Claude SWE-bench's gap; §6.3's failure-cost is the per-attempt-iteration component. The full-set Δcost is the sum; the unanimous-pass-conditional Δcost isolates the former.

**Methodology footnote (one line, compiled prose):** the per-arm cache-floor median recomputed on the unanimous-pass subset matches the full-set median in **`\result{agreement_matrix}{_all:_all:cache_floor_unchanged_majority}` of `\result{agreement_matrix}{_all:_all:cache_floor_total_groups}` (benchmark, seed, agent, arm) groups**; the two exceptions are Claude SWE-bench seed 2's `baseline` and `bash_only` arms, where the subset median is 360 tokens lower (≈$0.001/instance impact). **The `onlycode` arm — the contrast arm in the headline table — is byte-identical in every group**, so the floor is not driving the +14% → +4% collapse.

**Investigation note:** [`paper/q3_capability_tie_investigation.md`](q3_capability_tie_investigation.md) — agreement-matrix analysis with v1→v3 evolution, including the v3 finding that Claude SWE-bench's +14% cost gap collapses to +4% (NS) on the unanimous-pass subset (cost-of-failure, not cost-of-modification). See §11 + §12 of that file for the canonical §6 frame and the dual-mechanism decomposition table.

**Numbers:** [`paper/data/agreement_matrix.csv`](data/agreement_matrix.csv) (TO BE WRITTEN; per-cell unanimous-pass counts + split structure) and [`paper/data/headline_unanimous.csv`](data/headline_unanimous.csv) (TO BE WRITTEN; full-set vs unanimous-pass-subset headline contrasts, mirrors `paired_contrasts.csv` layout). Production script: promote `/tmp/q3_unanimous_only.py` and `/tmp/q3_headline_compare.py` to `paper/data/scripts/q3_unanimous_pass.py` once §6.3 cites the macros.

### 6.4 Benchmark reuse beyond this paper (~50 words / ~0.08 page)

One paragraph. The artifact-suite contract (§3.6) — deterministic / offline / seeded-random graders + materialize-time no-leak invariant — generalizes to other coding-agent benchmarks. State what a follow-up author would need to add a category or task: a `task.yaml`, a `workspace/`, a `grade(scratch_dir) → GradeResult` function obeying the four rules, and a `reference_output.*`. That's it. Do not re-spec the contract; cite §3.6.

### 6.5 Where the method works / doesn't (~80 words / ~0.13 page; was 4 paragraphs in pre-freeze draft, compressed for budget)

Honest accounting, compressed to ~3 sentences:

1. **Works for:** quantifying tool-surface tax under cache-noise (cache-adjusted methodology, §3.5); isolating regime effects via the artifact-vs-SWE-bench split; surfacing agent-design coupling (the significant same-regime divergence on SWE-bench — Codex *** vs Claude NS — between agents under an identical restriction).
2. **Doesn't work for:** claiming model-capability differences (pass rates are tied; we only measure path differences). Per-task pathology analysis is out of paper scope (decided 2026-05-28; the `analyze/` pipeline remains as harness instrumentation but does not land in the paper — see [paper/CLAUDE.md] for the rationale).
3. **One sentence on power:** per-cell SWE-bench breakdowns at n≈12-15 per repo are noisier than the headline n=100 — but per-repo breakdowns were **cut** from §5 in the 2026-05-28 restructure (former §5.5), so this caveat applies only to any per-repo claim made in compiled prose. Default: do not make per-repo claims.

### 6.6 Implications for agent design (~70 words / ~0.12 page)

Workshop audience expects actionable claims. **One prescriptive paragraph** that falls out of Table 1 + §5's four-cell cost structure (`code_only` cheaper or tied in 3 of 4 cells; SWE-bench/Claude the lone NS exception) + the §6.3 dual-mechanism decomposition:

- **If your tasks are computation-dominated:** drop the IDE surface; `code_only` wins on cost at parity capability (Artifact Claude cell).
- **If your tasks are modification-dominated with a high workload solve-rate:** the surface choice is roughly cost-neutral on Claude (unanimous-pass-conditional `code_only` Δcost is `\result{headline_unanimous}{swebench:claude:onlycode-vs-baseline:cost_adj:unanimous_majority_mean_delta_pct}` NS). The headline +14% penalty is a failure-cost effect on instances no surface can solve, not a per-edit tax on successful runs.
- **If your tasks are modification-dominated with a low solve-rate (Claude SWE-bench-like) AND you need a cost floor on failures:** keep `Edit`/`Write` at minimum — the path-cost edit-friction in §6.1 (Δoutput tokens stays at `\result{headline_unanimous}{swebench:claude:onlycode-vs-baseline:output_tokens:unanimous_majority_mean_delta_pct}` even on successes) compounds with the failure-cost in §6.3 on doomed runs to produce the +14% headline gap.
- **If your tool surface can be shaped so the agent batches multiple operations per call and paginates verbose outputs** (the Codex `code_only` pattern in §6.2): expect input-token savings that compound across iterations — provided your workload doesn't push LLM-call count up in the process.
- **Caveat the prescriptions:** H1 (batching) only pays off when the agent's API expresses it — empirically Codex does, Claude does not. H2 (upper-tail suppression) only pays off when the rival surface would produce verbose outputs in the first place. The solve-rate axis in the modification prescription matters because the failure-cost component in §6.3 scales with the fraction of unsolvable instances — workloads with near-100% solve-rates will not see it.

Hold drafting until §5.1 cells are frozen and the §6.2 `mcp_output_size.csv` + §6.3 `agreement_matrix.csv` / `headline_unanimous.csv` scripts have run.

---

## Drafting notes

- **No prose-level introduction.** §6 starts with the mechanism questions, not "In this section we discuss…". The opening of §6.1 (the question itself) doubles as the section opener.
- **Macros, not numbers.** Every cited value comes through `\result{edit_friction}{...}`, `\result{headline}{...}`, etc. Lint will catch bare digits. If a value isn't in a CSV yet, write the macro anyway and add the CSV cell — never inline the literal.
- **§6.1 lead must be ρ ≈ 0.49 (Δ_edit_chars), not the gold-patch ρ.** The gold-patch test is weaker (ρ ≈ 0.23) and the build pipeline doesn't expose it as a primary cell. If the prose drifts toward gold-patch as the headline, push back during review.
- **§6.2 mechanism is now H1 + H2, not "MCP output compression".** The original-outline hypothesis is falsified — see [`paper/q2_token_gap_investigation.md`](q2_token_gap_investigation.md). The draft can state H1 + H2 as confirmed, but the `mcp_output_size.csv` script must land before the macro placeholders in §6.2 resolve. The numerical values exist in the investigation file; promoting them into a CSV + `\result{...}` macros is mechanical, not analytical.
- **§6.3 is bounded by §5.4.** If §5.4's agreement matrix lands at <50% unanimous on SWE-bench, rewrite Q3's prediction line — don't draft against the wrong story.
- **§6.4–§6.6 are compressible.** First thing to cut if §6 overruns. The mechanism questions (§6.1–§6.3) are the intellectual contribution; the supporting bullets are framing.
- **No methodology rehashes.** §3 owns the cache-adjusted cost, the artifact-suite contract, and the integrity protocol. §6 cites them; it does not re-explain them.
- **No new mechanisms beyond Q1/Q2/Q3.** If a fourth mechanism question is tempting (e.g., "why does bash_only behave like X"), kill it in outline — there isn't room in 0.5 pages, and §5's metric surface (pass / cost / input-tok / output-tok) doesn't carry the data to support a fourth contrast cleanly.
- **`analyze/` pipeline stays out.** Same constraint as §3 (see [paper/CLAUDE.md]). No failure-mode taxonomy, no pattern-classifier subagents, no `patterns.json` reference. If a future draft introduces this material in §6, flag it as a regression.

---

## Overflow: what does NOT fit in §6 and where it goes instead

§6 has a 0.5-page target (0.75 ceiling). Most of the edit-friction (Q1) investigation has to land elsewhere. The placement map:

### Push to §7 Limitations
- **Edit-friction vs debug-loop confound.** The per-line tax is ~+22 tok/line on the both-PASS subset (n=37) but ~+63 tok/line on the both-FAIL subset (n=37). The current data cannot cleanly separate "edit verbosity proper" from "failed scripts → debug-iteration verbosity." Both are *consistent with* the edit-friction reading; we shouldn't claim isolation.
- **Codex `apply_patch` soft-disable** — empirically respected (4 leaks across 110 `code_only` logs in seed_1) but reviewers will ask. The disclosure already lives in §3.1; a one-line back-reference in §7 is enough.
- **Seed-1-only caveat** if seeds 2/3 aren't folded into `edit_friction.csv` by freeze (the production script averages whatever's in `all_results.csv`, but the gold-patch sizes don't change).

### Push to appendix
- The full 15-cell Spearman correlation table (5 metrics × 3 patch-size proxies, BH-corrected). Only `num_turns × patch_files_touched` survives FDR 0.05; the headline ρ in §6.1 is a *different* test and not part of that table.
- Per-arm within-arm slope fits (baseline ~7.5 tok/line OLS, code_only ~26.9 OLS; baseline ~127, code_only ~189 by Theil-Sen).
- Leverage-drop sensitivity table — slope difference *increases* on outlier-dropped subsets, opposite of reviewer intuition.
- The 4-bar median-split figure if a reviewer pushes back.

### Killed — do not include
- The "code_only's output-token slope is 3.6× baseline's" framing the investigation drafted first. OLS on R² < 0.01 is exactly what reviewers will pick apart, and the Theil-Sen/leverage results make the underlying point cleaner without the slope-ratio framing.
- The `bash_only` slope-gradient claim (baseline < bash_only < code_only) — pattern-matching, not a tested ordering.
- Artifact-as-clean-control framing. Soften to "consistent with edit-friction being SWE-bench-specific"; do not present as having isolated the mechanism (artifact differs from SWE-bench in many ways beyond edit-vs-write).

### Source-of-truth pointers
- Investigation writeup: [`paper/investigations/edit_friction_findings.md`](investigations/edit_friction_findings.md) (with opus-review responses, 2026-05-28).
- Production script: [`paper/data/scripts/edit_friction.py`](data/scripts/edit_friction.py) → [`paper/data/edit_friction.csv`](data/edit_friction.csv).
- Static input: [`paper/data/raw/swe_gold_patch_sizes.csv`](data/raw/swe_gold_patch_sizes.csv) (sourced once from HuggingFace, committed; do not regenerate at build time).
