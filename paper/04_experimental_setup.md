# 04 — Experimental Setup
# THIS IS A MORE DETAILED OUTLINE NOT THE ACTUAL PAPER DRAFT

**Role of this file.** Per-section outline. Compiled prose lives in `sections/04_experimental_setup.tex`; this file plans the structure and pinned content. Methodology (harness, integrity protocol, grader contract, cache/cost accounting) lives in §3; §4 carries (i) the inventory of what was actually run, (ii) the agent surfaces and arm-naming conventions, (iii) the seeds + inference-unit declaration that supports every comparison in §5, and (iv) the metric definitions, cost rates, and exclusion accounting.

**Page target:** 0.85 pages (ceiling 1.0), per [outline.md:20](outline.md#L20). The bump from 0.35 → 0.85 (2026-05-28) funds the §4.3 inference-unit defense, which had been under-budgeted relative to its reviewer-attack surface; 0.15 pg was pulled from §3.1+§3.2 and 0.35 pg from total slack — see [outline.md:26](outline.md#L26).

**Drafting rule.** All numbers — instance counts, per-category counts, model versions, CLI versions, wall budgets, per-Mtok rates, exclusion counts — come through `\result{...}` macros backed by `paper/data/*.csv`. No bare digits in the compiled `.tex`; `paper/lint.py` enforces this.

## Structure (4 subsections)

### 4.1 Benchmark inventory (~0.25 page)

Two tables, one paragraph apiece. No methodology — that lives in §3.3 (SWE-bench integrity) and §3.6 (artifact-suite contract).

**Artifact suite.** Total `\result{artifact_n_total}` tasks across nine categories, with per-category counts and a one-line "what capability does this category probe" per row, sourced from `paper/data/artifact_categories.csv`. Categories: `algorithmic`, `data_engineering`, `data_processing`, `data_science`, `enumeration`, `iterative_numerical`, `ml_engineering`, `stateful_reasoning`, `verification_heavy`. State that the suite covers the **computation regime** (single- and multi-file). Per-category breakdowns were cut from §5 in the 2026-05-28 restructure; the category list here describes benchmark scope, not a forward-reference to a results table.

**SWE-bench Mini.** Total `\result{swebench_n_total}` instances split into two sub-corpora: **verified-mini** (Django + Sphinx, a subset of SWE-bench Verified) and **datasci-mini** (sklearn + matplotlib + xarray + sympy + seaborn + astropy), with per-repo counts from `paper/data/swebench_repos.csv`. State that this covers the **modification / multi-file regime**. Per-repo breakdowns were cut from §5 in the 2026-05-28 restructure.

### 4.2 Agent surfaces and arm names (~0.15 page)

**Agent surfaces.** Two-row table with model ID, CLI version, and the invocation flags relevant to reproducibility:
- Claude Code — `claude-sonnet-4-6`, CLI version `\result{claude_cli_version}`, invoked with `--dangerously-skip-permissions --no-session-persistence`.
- Codex CLI — `gpt-5.5`, CLI version `\result{codex_cli_version}`, invoked with `--dangerously-bypass-approvals-and-sandbox`.

Codex is reported as a **co-headline finding** in §5.3 (Figure 2's four-bar cost-ratio panel exposes the agent-design dependence — the *significant* same-regime divergence is Codex *** vs Claude NS on SWE-bench), not as a footnote-level generalization probe. Stated here so the reader knows what to expect in §5.

**Arm names — consolidated paper convention.** Per the 2026-05-27 consolidation decision at [outline.md:221](outline.md#L221), the paper uses three names throughout:
- **`baseline`** — default tool surface, no restriction.
- **`bash_only`** — Bash plus read-only browsing primitives; all edit/write primitives disabled.
- **`code_only`** — MCP `execute_code` (+ `list_tools`) only; all native built-ins disabled.

DO NOT INCLUDE THIS SENTENCE IN THE PAPER, IT SHOULD JUST BE A README ON THE REPO INSTEAD:
One-sentence footnote on first use: *"The released harness uses the legacy names `tool_rich` and `onlycode` for `baseline` and `code_only` respectively; the paper uses the consolidated names throughout."* This is the only place that legacy-name disclosure lives. (kept so future agent's don't bring it up again)

### 4.3 Seeds and inference unit (~0.25 page)

This subsection supersedes the earlier "mean ± stderr over seeds" line in outline drafts. The choice of inferential unit is a substantive design decision that defends every comparison in §5; reviewers will check it.

**Seeds.** Three independent runs per `(instance, arm)` triple — `runs/swebench/full_run_seed_{1,2,3}/` and `runs/artifact/full_run_seed_{1,2,3}/`. Counts pinned via `\result{n_seeds}`.

**Unit of inference is the task, not the seed.** Seeds within a `(task, arm)` cell are replicates of the *same task*, not independent samples of the population of interest; treating them as the unit of inference inflates n and confuses noise sources. Procedure for every comparison in §5:

1. **Collapse seeds within each `(task, arm)` cell to a per-task mean.** Seed-level values are derivable from the released CSVs but are not reported in the paper body.
2. **For each ordered arm pair (A, B) within a benchmark**, compute the per-task vector of differences Δ_t = mean_A(t) − mean_B(t). Report **mean Δ, SE_Δ = SD(Δ)/√n_tasks, and a 95% CI** (normal approximation, n ≥ 93).
3. **Pair the CI with a paired Wilcoxon signed-rank p-value** on the Δ vector for continuous metrics (cost, turns, token counts). Wilcoxon is preferred over the paired t-test because per-task distributions are heavy-tailed — a handful of pathological SWE-bench instances dominate parametric variance while the median direction is clear.
4. **Pass rate** uses the same machinery on per-task pass rates ∈ {0, 1/3, 2/3, 1} — a Wilcoxon-on-rates analogue of McNemar that respects the 3-seeds-within-task structure.
5. **Marginal per-arm summary** (the "row" in the headline table at §5.1) is `mean over tasks of the per-task mean ± SD_task / √n_tasks` — the SE that respects task as the unit of replication.

Implementation: `paper/data/scripts/paired_contrasts.py`, reproducible from the released JSONL records.

### 4.4 Metrics, cost rates, and exclusions (~0.20 page)

**Metrics.** The §5 headline table reports four paired-difference columns per `(benchmark, agent)` cell — pass rate plus three resource axes. Defined here so §5 can be read against a fixed metric surface:
- **Pass rate** — `PASS / (PASS + FAIL)`; `env_fail` excluded from the denominator (see exclusions below). Reported as an absolute Δ in percentage points.
- **Cache-adjusted cost** — per §3.5, charging the shared per-arm prefix at the cache-read rate using the per-arm median first-turn `cache_read_input_tokens` floor. The token-based formula defined in §3.5 is retained for reference; the headline column is the cache-adjusted variant. Reported as relative Δ% in §5.
- **Input tokens** — per-run sum of `input_tokens` across user-role API turns (cached + uncached). Reported as relative Δ% in §5.
- **Output tokens** — per-run sum of `output_tokens` across user-role API turns. Reported as relative Δ% in §5.

**Per-Mtok rates.** Compact table of input / cached-input / output rates per model, sourced from `paper/data/cost_rates.csv`. These are the constants plugged into the §3.5 cost formula; pinning them in §4 makes every cost column in §5 reproducible from raw JSONL records.

**Wall budget.** `\result{wall_budget_seconds}` per `(instance, arm, run)` — same value as §3.2, restated here for the stats block.

**Exclusions.**
- `env_fail` — pre-flight `pytest --collect-only` returns zero items. Excluded from pass-rate denominators per Issue #238; counts reported separately in §5.
- **Auth re-runs.** 12 SWE-bench instances (sympy + mwaskom) hit ChatGPT-login authentication failures in seed_1 and were re-run on the same harness commit; one-line disclosure here, full accounting in §7. These results **are** used in the headline numbers — re-run, not excluded.

---

## Drafting notes

- **No methodology in §4.** §3.3 owns the SWE-bench integrity protocol, §3.5 owns the cost methodology, §3.6 owns the artifact-grader contract. §4 cites these and reports the actual scope.
- **No results in §4.** Numbers appear only as `\result{...}` macros for *scope* (counts, versions, rates, wall budget). All empirical findings — pass rates, costs, token counts, audit propagation — belong to §5.
- **Tables, not prose, for the inventory.** Nine artifact categories + eight SWE-bench repos read better as compact tables than as paragraphs. Lint must require `\result{...}` for every cell.
- **§4.3 must defend the inference unit, not just declare it.** State why per-task pairing (not per-seed) and why Wilcoxon (not paired-t). This is the subsection the page-budget bump was for; do not under-spend.
- **Single source of truth for arm names.** §4.2 is the only place the legacy harness names (`tool_rich`, `onlycode`) appear in the paper. Don't reintroduce them in §3 or §5 captions.
- **No bare digits.** Lint will fail the build on any unmacroed number, exactly as in §3.

---

## Citations needed for §4

Single staging ground for citations that originate in §4. Same workflow as the staging block in [02_related_work.md](02_related_work.md#L186): inline metadata stays here until a human approves and copies into `paper/references.bib`. Per [CLAUDE.md](../CLAUDE.md), agents do not edit `references.bib` directly. Citation-key prefixes (`repo:` / `report:` / `blog:` / unprefixed for peer-reviewed) follow the 02 convention.

**Already staged in [02_related_work.md](02_related_work.md#L186) — reuse keys, do not duplicate:**

| §4 location | Use key | Status |
|---|---|---|
| §4.1 SWE-bench Mini (the substrate) | `jimenez2024swebench` | **Blocked** — still in 02 staging with `author list reconstructed, verify ICLR` TBD; §4 insertion gated on that being cleared. |
| §4.1 verified-mini ("a subset of SWE-bench Verified") | `report:openai2024swebenchverified` | ✓ in `references.bib`. |
| §4.2 Codex CLI repository | `repo:openai2026codex` | In 02 staging (vendor-docs block); gated on access-date re-fetch. **Reuse this key — do not stage a duplicate `repo:openai-codex` in §4.** |
| §4.3 Wilcoxon signed-rank (line 46) | `wilcoxon1945` | ✓ in `references.bib` (moved 2026-05-28). `\cite{wilcoxon1945}` not yet wired — `sections/04_experimental_setup.tex` is still a TODO stub; insert when §4.3 prose is drafted. |

> **Claude Code product cite — resolved 2026-05-28.** §4.2 uses the primary product cite `repo:anthropic2026claudecode` (staged below, previously the commented placeholder), **not** the `liu2026divecc` architectural survey. Rationale: parity with `repo:openai2026codex` (both rows of §4.2's agent-surface table point at vendor-published source repos, not third-party descriptions), and the `\result{claude_cli_version}` macro wants a vendor-anchored reproducibility target. `liu2026divecc` retains its §02 related-work cite as architectural taxonomy — it just is not the §4.2 anchor.

### Staging block — new entries originating in §4

These are the candidates a human reviewer should fix any `TBD` fields on, then copy into `paper/references.bib`. Until then, §4 prose must keep inline metadata (CLI name, version macro, vendor, URL) so each entry can be reconstructed from the section alone.

```bibtex
% ─── Agent surfaces (§4.2) ─────────────────────────────────────────────
%
% NOTE: `report:openai2026gpt55`, `report:anthropic2026sonnet46`, and
% `repo:anthropic2026claudecode` moved to `references.bib` on 2026-05-28
% after human verification. Both vendor "model card" cites resolved to
% *system cards* on verification --- type, title, howpublished, and url
% fields swapped accordingly. The Codex CLI repo cite is still NOT
% staged here --- reuse `repo:openai2026codex` from 02_related_work.md's
% staging block (same URL, vendor, artifact).

% ─── Statistical machinery (§4.3) ──────────────────────────────────────
%
% NOTE: `wilcoxon1945` and `mcnemar1947` both moved to `references.bib`
% on 2026-05-28. `wilcoxon1945` verified against
% JSTOR/Semantic Scholar/Shippensburg PDF; `mcnemar1947` verified
% against DOI 10.1007/BF02295996 (Springer/Cambridge Core),
% cross-checked with PubMed and IDEAS/RePEc. Both are tied to §4.3
% framing; drop `mcnemar1947` if the "Wilcoxon-on-rates analogue of
% McNemar" prose is removed from §4.3 during drafting. See the bib
% header for the full verification trail.

% ─── Per-Mtok cost rates (§4.4) ────────────────────────────────────────
%
% NOTE: `docs:anthropic2026pricing` and `docs:openai2026pricing` moved
% to `references.bib` on 2026-05-28 after human verification of both
% URLs; access date pinned to 2026-05-28 in each entry's note. See the
% bib header for the move log.
```

### `TBD` fields a human reviewer must resolve before insertion

- `repo:openai2026codex` — **owned by 02 staging block**, not §4. Access-date re-fetch is the gating action there; §4 just reuses the key.
