# 01 — Introduction
# THIS IS A MORE DETAILED OUTLINE NOT THE ACTUAL PAPER DRAFT

**Role of this file.** Paragraph-grain plan for §1. Compiled prose lives in [sections/01_introduction.tex](sections/01_introduction.tex); this file pins each paragraph's key claim, the exact citations it must carry, and the macros it pulls from `paper/data/*.csv`. Mirrors the style of [03_method.md](03_method.md) and [05_results.md](05_results.md).

**Page target:** ~1.0 pg (combined with abstract: 1.1 pg target, 1.35 ceiling — see [outline.md:17](outline.md#L17)). **Four paragraphs**, sized as below. No standalone roadmap paragraph — the contribution bullets carry the navigation work, per ML/SE convention; section headings tell the reader where each piece lands.

**Deviation from [outline.md §1](outline.md#L38)** — contribution ordering is now **agent-forward, mechanism-forward** (the four-cell agent-conditional cost structure leads; the three-mechanism decomposition follows; capability invariance closes). The artifact suite is §3.6 method, **not a §1 contribution** — the artifact-benchmark space is crowded (KernelBench, MLE-Bench, MLAgentBench, RE-Bench, SWE-Lancer, CORE-Bench; see §2.4) and a contribution claim would oversell a small piece of work. [outline.md:43-46](outline.md#L43) still encodes the older benchmark-first ordering — flag for sync.

**Bibliography is the staging block in [02_related_work.md §Staging](02_related_work.md#L186)** — every `\cite{...}` key referenced here is already present there; do **not** add new keys without a corresponding staging entry, and do **not** edit `paper/references.bib` directly (per [CLAUDE.md](../CLAUDE.md)).

**Drafting rule.** Numeric claims come through `\result` / `\respct` / `\resp` macros backed by the CSVs listed in the macro table below. Bare digits are a lint failure (see [paper/lint.py](lint.py)).

---

## Structure (4 paragraphs, ~1 page)

### ¶1 — The phenomenon: three contradictory claims about tool-surface design (~5 sentences, ~0.20 pg)

**Hook.** Open with the observation that coding agents now ship with overlapping tool surfaces (Read/Grep/Glob/Edit/Write/Bash on Claude Code, ACI primitives on SWE-agent, MCP `execute_code` on emerging stacks), and the field has settled on three mutually incompatible claims about which surface a coding agent should expose:

1. **Specialized IDE primitives are *required*.** SWE-agent argues the Agent-Computer Interface (ACI) is load-bearing — the ACI-vs-shell ablation showed a +10.7 pp gain on SWE-bench at the time of publication. \cite{yang2024sweagent}
2. **Bash is *sufficient*.** mini-SWE-agent is a ~100-line bash-only scaffold that posts >74% on SWE-bench Verified — no IDE primitives at all. \cite{repo:miniswagent}
3. **Replace the tool surface with code execution.** Industry write-ups report 98–99% token reductions by routing through an MCP `execute_code` tool rather than calling the native tools directly. \cite{blog:anthropic2025codemcp, blog:cloudflare2025codemode, blog:cloudflare2026codemodemcp}

**Pivot sentence.** "The three claims have never been crossed on a single harness, on the same model, with regime stratification — so the field cannot tell which condition each prescription applies under, or whether they contradict each other at all." This is the gap §1 sells.

**Citations (¶1).** `yang2024sweagent`, `repo:miniswagent`, `blog:anthropic2025codemcp`, `blog:cloudflare2025codemode`, `blog:cloudflare2026codemodemcp`. All staged ([02_related_work.md:237, 338, 298, 307, 317](02_related_work.md)).

**Anti-patterns.** Do NOT lead with "tool restriction" framing — the agent-conditional four-cell pattern is the contribution, not "we removed tools and looked." Do NOT cite the Cloudflare 99.9% figure as if it transfers to coding agents; it is on a 2,500-endpoint enterprise API surface (see §2 delta). Do NOT name external-MCP vs. internal-IDE as the headline distinction here — that contrast is §2 work; §1 just notes the three claims exist.

---

### ¶2 — The detection axis we work in (~5 sentences, ~0.20 pg)

**Claim.** Same harness, same model, same prompts, three tool surfaces (`baseline` / `bash_only` / `code_only`) × two task regimes (computation, modification) × two agents (Claude Code, Codex CLI), evaluated under integrity-clean SWE-bench protocol (post-agent `test_patch` application; full defense in §3.3). The crossed 3×2×2 is the minimum design that disambiguates the three claims above.

**Arm definitions (one clause each, expanded in §3.1).** `baseline` = default Claude Code / Codex tool surface; `bash_only` = native bash + read/glob/grep, no Edit/Write; `code_only` = single MCP tool `mcp__codebox__execute_code` on a persistent Python+Bash REPL, all native built-ins disallowed. **Use the consolidated arm trio per the [2026-05-27 decision](outline.md#L257)** — do **not** use `tool_rich` / `onlycode` legacy names in compiled prose.

**Regime cells (one clause each, expanded in §3.6 / §4).** **Modification** cell = SWE-bench Mini (100 instances; canonical post-agent `test_patch` protocol). **Computation** cell = a set of tasks each defined by a `(workspace/, hidden grader, reference output)` triple with deterministic offline scorers — contract in §3.6, per-category counts in §4. The computation cell is a methodological vehicle, not a benchmark contribution (¶4 / [outline.md L43-46 deviation note](outline.md#L43)).

**Citations (¶2).** `jimenez2024swebench` (the substrate and the canonical protocol), `anthropic2024mcp` (the protocol the `code_only` arm is built on; cite once at the arm definition so the reader treats `code_only` as a realistic deployment configuration, not a research one-off). All staged ([02_related_work.md:200, 225](02_related_work.md)).

**Anti-patterns.** Do NOT defend the artifact suite as a contribution here — the contract is §3.6 work; the regime-cell sentence is a forward reference only. Do NOT enumerate seeds / instance counts here — §4 is the stats block. Do NOT preview §3.3's pre-apply cleanup or §3.5's cache methodology; one sentence each at most.

---

### ¶3 — What's already known about tool-surface effects (~5 sentences, ~0.20 pg)

**Claim.** Walk the prior data points that touch this axis and show that none of them is the crossed comparison we are running. Compress aggressively at draft time — prose target is 5 sentences, not 5 bullets. Suggested merge: collapse SWE-agent + mini-SWE-agent into one sentence, the three blog citations into one sentence, Liu + Verdent into one sentence, then close with the "nobody crossed three internal IDE surfaces under regime stratification with both Claude and Codex" pivot.

- **SWE-agent.** Two-arm ACI-vs-shell on 2024 models; no code-execution arm, no regime stratification. \cite{yang2024sweagent}
- **mini-SWE-agent.** Single bash-only arm on SWE-bench Verified; no comparison to richer surfaces on the same harness, no code-execution arm. \cite{repo:miniswagent}
- **Industry blog reports.** External-MCP tool surfaces (Drive, Salesforce, Stripe, Cloudflare API), not internal IDE primitives; no benchmark, no regime stratification. \cite{blog:anthropic2025codemcp, blog:cloudflare2025codemode, blog:cloudflare2026codemodemcp}
- **"Dive into Claude Code".** Architectural taxonomy of Claude Code's primitives — explicitly without ablation. \cite{liu2026divecc}
- **Verdent technical report.** Single-vendor informal ablation; no public methodology, no regime split. \cite{report:verdent2025swebench}

**Optional adjacency to mention if length permits (1 clause max).** Live-SWE-agent (\cite{xia2025liveswagent}) ablates scaffold self-evolution, not tool surface — different axis. Terminal Agents Suffice (\cite{bechard2026terminal}) makes the parallel "less is more" argument on enterprise APIs (not code repair). Cite as adjacencies, not direct precedents.

**Citations (¶3).** `yang2024sweagent`, `repo:miniswagent`, `blog:anthropic2025codemcp`, `blog:cloudflare2025codemode`, `blog:cloudflare2026codemodemcp`, `liu2026divecc`, `report:verdent2025swebench`. Optional adjacencies if length allows: `xia2025liveswagent`, `bechard2026terminal`. All staged.

**Anti-patterns.** Do NOT relitigate the full §2 distinction list — §1 names the gap; §2 defends the delta. Do NOT misattribute the tool-use tax framing to Wang et al.; it is **Zhang et al.** — and the framing belongs in ¶4, not here. (See [02_related_work.md citation hygiene note at L99](02_related_work.md#L99).)

---

### ¶4 — Contributions, agent-forward and mechanism-forward (~10 sentences, ~0.35 pg)

**Structural rule.** Three numbered bullets ordered to lead with the empirical observation about agents, then the causal explanation, then the dissociation that ties it together. **Agent-forward / mechanism-forward ordering supersedes the earlier "benchmark-first" rule in [outline.md:43](outline.md#L43)** — the artifact suite is methodology (§3.6), not a §1 contribution. The artifact-benchmark space is crowded (KernelBench, MLE-Bench, MLAgentBench, RE-Bench, SWE-Lancer, CORE-Bench — see §2.4); selling our v1 suite as a contribution oversells a small piece of work. The strong, differentiated claims are the four-cell agent-conditional structure and the three-mechanism decomposition.

#### Contribution 1 — A four-cell agent-conditional cost structure.

Across the four (regime, agent) cells, `code_only` is the cheaper arm in 3 of 4, but **directionally more expensive on the lone fourth cell — Claude × SWE-bench**. Macros:

| Cell | Contrast | Macro for headline % |
|---|---|---|
| Artifact / Claude | `code_only` vs `bash_only` | `\respct{paired_contrasts}{artifact:claude:code_only-vs-bash_only:cost_adj:mean_delta}{artifact:claude:code_only-vs-bash_only:cost_adj:mean_b}` (***, p = `\resp{paired_contrasts}{artifact:claude:code_only-vs-bash_only:cost_adj:wilcoxon_p}`) |
| Artifact / Codex  | `code_only` vs `bash_only` | `\respct{paired_contrasts}{artifact:codex:code_only-vs-bash_only:cost_adj:mean_delta}{artifact:codex:code_only-vs-bash_only:cost_adj:mean_b}` (directional) |
| SWE-bench / Codex | `code_only` (a.k.a. `onlycode`) vs `baseline` | `\respct{paired_contrasts}{swebench:codex:onlycode-vs-baseline:cost_adj:mean_delta}{swebench:codex:onlycode-vs-baseline:cost_adj:mean_b}` (***, p = `\resp{paired_contrasts}{swebench:codex:onlycode-vs-baseline:cost_adj:wilcoxon_p}`) |
| **SWE-bench / Claude** (anomaly) | `onlycode` vs `baseline` | **+**`\respct{paired_contrasts}{swebench:claude:onlycode-vs-baseline:cost_adj:mean_delta}{swebench:claude:onlycode-vs-baseline:cost_adj:mean_b}` (NS) |

**Key claim.** The same restriction (`code_only`) wins under three (regime, agent) combinations and loses under one — **surface choice is jointly determined by regime AND agent design, not by either alone**. The prior literature's mutually contradictory claims (¶1) coexist because each is true under its specific (regime, agent) combination and false under the others. **Prose rule: lead with the four-cell *shape*, not any individual cell's magnitude.** Capability invariance (Contribution 3) is what guarantees the shape is a cost claim, not a capability claim.

**Note on legacy arm names in CSV keys.** `paired_contrasts.csv` retains the on-disk harness names (`onlycode`, `tool_rich`) per the [2026-05-27 decision](outline.md#L256); the **rendered prose** still says `code_only` / `baseline`. The mapping is a one-line rename at the data-layer boundary; do not be tempted to also rename the keys — that would invalidate the run corpus.

#### Contribution 2 — A three-mechanism causal decomposition.

Decompose the four-cell structure into three causally distinct mechanisms whose joint footprint matches it; **no single mechanism predicts the full table**.

1. **Path-cost (edit friction).** `code_only` must express every file edit as a Python script; on Claude SWE-bench this scales output tokens with edit volume — per-instance Spearman ρ = `\result{edit_friction}{rho_edit_chars}` (p = `\resp{edit_friction}{rho_edit_chars_p}`). Drives the Claude × SWE-bench output-token blow-up. Forward to §6.1.
2. **Failure-cost.** The Claude × SWE-bench cost overrun localizes to unanimous-fail / split instances. On the unanimous-pass subset the gap collapses from the headline ~+14% to ~+4% (NS); the headline lives on doomed-run trajectories, not per-task cost of modification. Forward to §6.3 / §5.4. *(Numbers come through `\result{headline_unanimous}{swebench:claude:onlycode-vs-baseline:cost_adj:unanimous_majority_mean_delta_pct}` once the CSV ships — see "blocked macros" below.)*
3. **Pricing asymmetry.** On Codex, `execute_code` batches operations per LLM call (~2.5 tool calls per LLM step vs ~1.0 for `baseline`) and paginates verbose outputs, producing the SWE-bench / Codex win without changing LLM-call count. Codex-only — Claude does not batch on either benchmark. Forward to §6.2.

**Prose rule.** One sentence per mechanism, name the cells each mechanism is responsible for, forward to the §6.x section. Do not preview the §6.x evidence — the mechanisms are *named* here, *defended* there.

#### Contribution 3 — Capability invariance, with empirical receipt.

Pass rates differ by <3 pp across all 4 cells × 3 arms (all NS in Table 1's pass column), and on a strict 9/9-trial unanimity criterion, the majority of instances in every cell are unanimously decided — task outcome does not vary with tool surface for the bulk of the corpus. **Tool surface changes the path and the cost, not the answer.** This is the dissociation that lets Contributions 1 and 2 be read as cost-engineering claims rather than capability claims, and lets §6's prescriptive guideline talk about surface choice as a cost axis orthogonal to model capability. Consistent with the Capability Overlap Principle (\cite{zhang2026tooltax}); the load-bearing claim is the empirical agreement-matrix result, not the theoretical frame.

**Macros to cite.**

- Aggregate pass-NS: cite implicitly via "all four `:pass:wilcoxon_p` p-values NS" — the §5.1 table already carries the four numbers; do not re-quote them in §1.
- Unanimous-decided fraction: forward-reference §5.4. **Blocked on [paper/data/agreement_matrix.csv](data/agreement_matrix.csv) (§5.4 unblock; see [outline.md:234](outline.md#L234)).** Until it ships, write the qualitative claim ("the majority of instances are unanimously decided across all nine trials") and leave a `% TODO macro` marker.

**Citations (¶4).** `zhang2026tooltax` (one cite, Contribution 3 framing only). No others — Contributions 1 and 2 are empirical results from this paper's data.

**Anti-patterns.**

- Do NOT include "we built a new benchmark" as a contribution — the artifact suite is methodology (§3.6); the space is crowded with KernelBench / MLE-Bench / MLAgentBench / RE-Bench / SWE-Lancer / CORE-Bench (§2.4 positions us against them). One forward reference in ¶2, then move on.
- Do NOT lead with capability invariance; the four-cell agent-conditional structure is the headline.
- Do NOT use the phrase "Code Mode hypothesis" — the agent-conditional four-cell pattern *supersedes* that framing (see [CLAUDE.md "Paper Writing"](../CLAUDE.md)); reading any doc that uses the old framing risks importing stale language.
- Do NOT cite the §6.1 OLS "3.6× slope ratio" framing — R² < 0.01 within-arm, reviewers will catch it. Use Spearman ρ ([outline.md:143](outline.md#L143)).
- Do NOT lean on Artifact as a clean control for the SWE-bench edit-friction reading — the two benchmarks differ in many ways beyond edit-vs-write (codebase size, persistent kernel, test setup). Soften to "consistent with" (per [outline.md:145](outline.md#L145)).
- Do NOT preview the §6.6 prescriptive guideline — that is the discussion close. §1 names the mechanisms; §6 sells the prescription.

---

## Citation map for §1

| `\cite{...}` key | Used in | Status in staging block ([02_related_work.md](02_related_work.md)) | Notes |
|---|---|---|---|
| `yang2024sweagent` | ¶1, ¶3 | Verified ([L237](02_related_work.md#L237)) | NeurIPS 2024 — claims ACI required, +10.7 pp |
| `repo:miniswagent` | ¶1, ¶3 | URL verified, no paper ([L338](02_related_work.md#L338)) | bash-only, >74% SWE-bench Verified |
| `blog:anthropic2025codemcp` | ¶1, ¶3 | Verified ([L298](02_related_work.md#L298)) | ~98.7% token reduction (Drive/Salesforce/Stripe) |
| `blog:cloudflare2025codemode` | ¶1, ¶3 | Authors verified ([L307](02_related_work.md#L307)) | Sept 2025; ~99.9% on Cloudflare API |
| `blog:cloudflare2026codemodemcp` | ¶1, ¶3 | Verified ([L317](02_related_work.md#L317)) | Feb 2026 follow-up |
| `jimenez2024swebench` | ¶2 | Verified ([L200](02_related_work.md#L200)) | Substrate + canonical post-agent `test_patch` protocol |
| `anthropic2024mcp` | ¶2 | Verified ([L225](02_related_work.md#L225)) | Protocol cite at arm definition |
| `liu2026divecc` | ¶3 | Verified ([L430](02_related_work.md#L430)) | Architectural taxonomy without ablation |
| `report:verdent2025swebench` | ¶3 | Verified ([L327](02_related_work.md#L327)) | Informal single-vendor ablation |
| `xia2025liveswagent` | ¶3 (optional adjacency) | Verified ([L346](02_related_work.md#L346)) | Drop if length tight |
| `bechard2026terminal` | ¶3 (optional adjacency) | Verified ([L250](02_related_work.md#L250)) | Drop if length tight |
| `zhang2026tooltax` | ¶4 (Contribution 3) | Verified ([L417](02_related_work.md#L417)) | Capability Overlap Principle — citation hygiene: **Zhang**, not Wang |

**Hard rule.** Every key in this table is already in the staging block — no new BibTeX entries are needed for §1. If a draft pulls in a key outside this table, the author must first add a staging entry in [02_related_work.md](02_related_work.md) with enough metadata for a human to verify in under 30 seconds; do **not** edit [references.bib](references.bib) directly (per [CLAUDE.md](../CLAUDE.md) "Never edit `paper/references.bib` directly").

**Intentionally not cited in §1.** The following are §2 or §3 work and should not leak into the intro:

- Agentless / AutoCodeRover / Moatless — scaffold prior art, §2.
- PAL / PoT / CodeAct / OpenHands — code-as-action lineage, §2.
- MLE-Bench / MLAgentBench / RE-Bench / SWE-Lancer / CORE-Bench — computation-regime benchmark precedents, §2.4. These are the "other artifact benchmarks" that motivate the demotion of the artifact-suite from §1 contribution to §3.6 method (¶4 rule).
- SWE-Bench Pro / Multi-SWE-bench / SWE-PolyBench / SWE Atlas — stratified-SWE-bench precedents, §2.
- SWE-Effi — efficiency framing, §2 / §6.
- `aidev2026` (workshop anchor dataset) — paragraph-grain positioning lives in §2; in §1 the contribution language stays "controlled-ablation complement" and the AIDev cite is held until the staging block clears its TBDs ([02_related_work.md:684](02_related_work.md#L684)).
- The Cloudflare 99.9% figure — quote in the prose at most once, in ¶1, and only as the "98–99%" range; do not re-cite in ¶3.

---

## Macro map for §1

Headline-table macros all live in `paper/data/paired_contrasts.csv` ([2026-05-27 decision](outline.md#L248)); a `\result` / `\respct` / `\resp` lookup against the keys below resolves once `make values` regenerates `paper/generated/values.tex`.

| Claim | Macro |
|---|---|
| Artifact / Claude cost-adj % | `\respct{paired_contrasts}{artifact:claude:code_only-vs-bash_only:cost_adj:mean_delta}{artifact:claude:code_only-vs-bash_only:cost_adj:mean_b}` |
| Artifact / Claude cost-adj p | `\resp{paired_contrasts}{artifact:claude:code_only-vs-bash_only:cost_adj:wilcoxon_p}` |
| Artifact / Codex cost-adj % | `\respct{paired_contrasts}{artifact:codex:code_only-vs-bash_only:cost_adj:mean_delta}{artifact:codex:code_only-vs-bash_only:cost_adj:mean_b}` |
| SWE-bench / Codex cost-adj % | `\respct{paired_contrasts}{swebench:codex:onlycode-vs-baseline:cost_adj:mean_delta}{swebench:codex:onlycode-vs-baseline:cost_adj:mean_b}` |
| SWE-bench / Codex cost-adj p | `\resp{paired_contrasts}{swebench:codex:onlycode-vs-baseline:cost_adj:wilcoxon_p}` |
| SWE-bench / Claude cost-adj % (anomaly) | `\respct{paired_contrasts}{swebench:claude:onlycode-vs-baseline:cost_adj:mean_delta}{swebench:claude:onlycode-vs-baseline:cost_adj:mean_b}` |
| Edit-friction Spearman ρ | `\result{edit_friction}{rho_edit_chars}` |
| Edit-friction Spearman p | `\resp{edit_friction}{rho_edit_chars_p}` |

**Blocked macros (do not write into §1 prose until shipped):**

- `\result{headline_unanimous}{swebench:claude:onlycode-vs-baseline:cost_adj:unanimous_majority_mean_delta_pct}` — for the ~+4% NS unanimous-pass-conditional number in Contribution 2, mechanism (2). Blocked on [paper/data/headline_unanimous.csv](data/headline_unanimous.csv); production script `paper/data/scripts/q3_unanimous_pass.py` needs promotion (see [outline.md:234](outline.md#L234)).
- `\result{agreement_matrix}{...:unanimous_strict_pct}` / `...:unanimous_majority_pct` — for the "majority unanimously decided" line in Contribution 3. Blocked on [paper/data/agreement_matrix.csv](data/agreement_matrix.csv) (same CSV blocker).
- **Author guidance until those land:** state the qualitative claim in ¶4 ("the majority of instances are unanimously decided across all nine trials"; "the headline gap collapses on the unanimous-pass subset") and leave a `% TODO macro` marker for the second pass. Compile-pass through lint will pass because no bare digit appears.

**Macros not used in §1 (resist the temptation):**

- `paired_contrasts` `:input_tokens:` / `:output_tokens:` keys — Contribution 2 names "+40% output tokens" only as an aggregate aside; the per-token decomposition belongs to §5.1 ¶2 (per [05_results.md:46](05_results.md#L46)) and §6.1. §1 must not anchor on token-channel numbers.
- `paired_contrasts` `:pass:mean_delta` keys — the four pass-NS rows are Table 1 work, not §1 work. §1 says "all NS" qualitatively.
- `paired_contrasts` `:turns:` keys — turn counts are not headline metrics ([05_results.md:119](05_results.md#L119)); they do not appear in §1.

---

## Drafting checklist

Before circulating a §1 draft:

1. **All four paragraphs present.** Phenomenon → detection axis → prior data → contributions (3 bullets). No roadmap paragraph — contribution bullets carry the navigation.
2. **Contribution ordering: agent-forward, mechanism-forward.** Four-cell cost structure → three-mechanism decomposition → capability invariance. Do not lead with the artifact suite — it is §3.6 method, not a §1 contribution.
3. **No bare digits.** Every numeric claim resolves through a macro from the table above, or is qualitative pending a blocked-macro unblock.
4. **Citation hygiene.** Zhang et al., **not** Wang et al., for the tool-use tax framing.
5. **Arm naming.** `baseline` / `bash_only` / `code_only` in prose; legacy `tool_rich` / `onlycode` only inside CSV-key strings.
6. **Forward references only.** §1 names §3.3 (integrity), §3.5 (cost), §3.6 (artifact contract), §5 (results), §6.1 / §6.2 / §6.3 (mechanism questions) — it does **not** preview their evidence.
7. **No paper-out-of-scope content.** Per the [2026-05-28 decision in CLAUDE.md](../CLAUDE.md), the `analyze/` pathology pipeline is excluded from the paper; §1 contributions list **does not** mention failure-mode taxonomy, pattern classification, or subagent classifiers. If draft prose drifts into pathology language, revert and re-read the decision-log entry in [outline.md:262](outline.md#L262).
8. **Length.** Compile, measure, prune. Target 1.0 pg; ceiling 1.35 (combined with abstract, target 1.1 / ceiling 1.35).
