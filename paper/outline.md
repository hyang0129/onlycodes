# Paper Outline — KDD 2026 Agentic AI Evaluation & Trustworthiness Workshop

**Target venue:** [KDD 2026 Workshop on Evaluation and Trustworthiness of Agentic AI](https://kdd-eval-workshop.github.io/agenticai-evaluation-kdd2026/)
**Submission deadline:** **2026-06-01 AOE** (7 days from 2026-05-25)
**Notification:** 2026-07-01
**Camera-ready:** 2026-07-10
**Workshop:** 2026-08-09 or 08-10, ICC Jeju, Korea
**Format:** ACM Conference Proceeding template (`acmart` class), 9 pages excl. references, anonymous, OpenReview submission
**Archival:** Posted on workshop website only — **not** included in KDD proceedings (good for double-submission optionality)

## Page budget (target ~7.5 pages, not 9)

The 9-page limit is the ceiling, not the goal. Dense > stuffed; reviewers prefer tight claims over hedged filler. Each extra page is more reviewer-2 surface area. Saving 1.5 pages of slack also lets figure sizes breathe.

| Section | Target | Hard ceiling |
|---|---|---|
| Abstract + §1 Introduction | 1.25 | 1.5 |
| §2 Related Work | 0.75 | 1.0 |
| §3 Method (incl. §3.3 integrity disclosure) | **1.75** | 2.0 |
| §4 Experimental Setup | 0.5 | 0.75 |
| §5 Main Results | 2.0 | 2.25 |
| §6 Redundancy Table (Table 1 + short prose) | 0.5 | 0.75 |
| §7 Discussion (3 prescriptions) | 0.5 | 0.75 |
| §8/Limitations (required) | 0.25 | 0.5 |
| **Total** | **7.5** | 8.5 (with all ceilings hit) |

**The non-negotiable budget item is §3.3** — the post-Issue #287 integrity disclosure. Compressing this to a parenthetical to save space invites a reviewer-2 attack on the test-patch protocol. Keep it ≥0.5 page even if other sections shrink.

**§3.5 (cache isolation methodology) is the other defensive paragraph** — without it, a reviewer will read the cost table and ask "but isn't OpenAI's prompt cache non-deterministic?" Pre-empt it with one tight paragraph (~5-7 sentences); see §3 sub-outline for content.

Structural skeleton only. Each section lists what the prose will cover, not the prose itself. `[bracketed]` items mark spots where the author decides whether to import from planning docs (issue #158, `docs/ROADMAP.md`, `paper/02_related_work.md`).

---

## Abstract (~180 words)

- One-sentence framing: modern coding agents expose multiple tool surfaces (IDE primitives, bash, MCP execute_code) — which surface is actually load-bearing on which task?
- One-sentence statement of method: integrity-clean three-arm ablation (`tool_rich` / `bash_only` / `code_only`) on artifact-graded computation tasks and SWE-bench Mini modification tasks, two agent surfaces (Claude Code, Codex CLI).
- One-sentence statement of comparison classes: SWE-agent's ACI claim (NeurIPS 2024), mini-SWE-agent's bash-only result (2025), Anthropic/Cloudflare "Code Mode" external-MCP claims.
- One-sentence headline: cost asymmetry flips sign between regimes — code_only wins by 33% on computation tasks, tool_rich wins by 11% on modification tasks, pass rates statistically tied within each regime.
- One-sentence claim: the sign-flip is predicted by the Capability Overlap Principle (Zhang et al. 2026) and supports a *regime-dependent* optimal tool surface rather than the "less is more" or "ACI wins" framings.
- **Do not finalize until §5 numbers freeze.** Abstract is written last.

---

## 1. Introduction (~1 page; combined with abstract: 1.25 page target)

- **The phenomenon.** Coding agents ship with overlapping tool surfaces — Claude Code's Read/Grep/Glob/Edit/Write/Bash, Cursor's equivalents, the SWE-agent ACI. Industry blogs (Anthropic Nov 2025, Cloudflare Sept 2025 / Feb 2026) report 98–99% token reductions by routing through `execute_code` MCP tools; academic work (SWE-agent NeurIPS 2024) argues specialized IDE tools are *required*; mini-SWE-agent (2025) shows bash-only is sufficient. **The field has three contradictory claims and no crossed comparison.**
- **The detection axis we work in.** Same harness, same model, same prompts, three tool surfaces × two task regimes. Integrity-clean evaluation (post-Issue #287 protocol — `test_patch` applied post-agent, restoring standard SWE-bench semantics).
- **What's already known about tool-surface effects.** SWE-agent's two-arm ACI-vs-shell result, mini-SWE-agent's single-arm bash result, Anthropic/Cloudflare's external-MCP token reduction, "Dive into Claude Code" (Liu et al. 2026)'s architectural taxonomy *without ablation*, Verdent's anecdotal informal ablation. Nobody has crossed the three surfaces with regime stratification.
- **Our contribution (3 bullets, paper-claim-aligned).**
  1. **A regime-dependent sign-flip:** on computation-dominated tasks, `code_only` is ~33% cheaper than `tool_rich` at equal pass rate; on modification-dominated multi-file tasks, `tool_rich` is ~11% cheaper than `code_only` at equal pass rate. (Same model, same harness, same prompts — the regime is the only varied factor.)
  2. **Capability invariance within regime.** Pass rates are statistically tied across all three arms within each regime. The asymmetry lives in cost/turns, not in capability — supporting the Capability Overlap Principle (Zhang et al. 2026) framing where IDE tool gain depends on whether primitives have unique non-bash-redundant capability *for this task shape*.
  3. **Agent-design dependence (secondary).** Codex CLI shows a different SWE-bench ranking than Claude Code (`code_only` cheaper than `tool_rich`), suggesting optimal tool surface is jointly determined by regime AND agent design — not a universal "less is more" or "ACI wins."
- **Roadmap of the paper.** One paragraph.

---

## 2. Related Work (0.75 page target; 1.0 ceiling)

Detailed outline in [02_related_work.md](02_related_work.md). Three subsections:

- **2.1 IDE-tool-surface ablation on coding agents.** SWE-agent (Yang et al. NeurIPS 2024, ACI vs shell, +10.7pp); mini-SWE-agent (2025, bash-only ≥74% on Verified); Live-SWE-agent (Xia et al. 2511.13646, scaffold evolution); Liu et al. (2604.14228, Claude Code design space without ablation); Rombaut (2604.03515, source-code taxonomy of 13 OSS scaffolds); Verdent (informal). **Delta:** none of these run the crossed three-surface design under integrity-clean evaluation with regime stratification.
- **2.2 Code-execution-as-action / code-mode.** CodeAct (Wang et al. ICML 2024, code-as-action vs JSON tools at the *encoding* level); OpenHands/CodeAct 2.1 (2511.03690); Anthropic "Code execution with MCP" (Nov 2025, external tools); Cloudflare "Code Mode" / "Code Mode MCP" (Sept 2025 / Feb 2026, external APIs); Terminal Agents Suffice (Bechard et al. 2604.00073, enterprise APIs). **Delta:** all studied **external** tool surfaces. Nobody crossed three internal IDE-tool surfaces on coding benchmarks with regime stratification.
- **2.3 Tool-use tax / capability overlap.** Zhang et al. *Are Tools All We Need? Unveiling the Tool-Use Tax in LLM Agents* (arXiv:2605.00136, Apr 2026) — the theoretical frame (general-purpose math/QA, not coding). Tool-pruning literature (Budget-Aware Tool Use 2511.17006, ToolTree 2603.12740, Trajectory Reduction 2509.23586) is orthogonal (selection problem, not surface design). MCP tool descriptions ablations (2602.14878) ablate *description text*, not the tool set.

End with one sentence positioning this work as the missing empirical complement to Liu et al. (2604.14228) — they describe Claude Code's tool architecture, we ablate it on SWE-bench.

---

## 3. Method (1.75 page target; 2.0 ceiling — §3.3 integrity disclosure is non-negotiable)

Sub-outline pending in `03_method.md` (TODO). Summary structure:

- **3.1 Three-arm tool surface.** Define each:
  - `tool_rich`: full Claude Code IDE surface (Read, Grep, Glob, Edit, Write, Bash, plus all built-in agents/skills).
  - `bash_only`: Bash only, all IDE primitives disallowed via `--disallowedTools`. mini-SWE-agent's tool surface, ported to our harness.
  - `code_only`: single MCP tool `mcp__codebox__execute_code` (Python + Bash, persistent REPL kernel). All built-in tools disallowed.
- **3.2 Harness design.** Subprocess isolation (`run_claude` creates temp `CLAUDE_CONFIG_DIR`), per-arm overlay refresh (fuse-overlayfs upper+work reset between arms), per-instance venv (outside overlay), git-history strip (single orphan commit, no reflog, no `base_commit` recoverability), **per-task prompt-cache isolation (`--cache-isolation`) injecting a deterministic 16-hex nonce into the codex tools array so every (instance, arm, run) triple is a cold-cache measurement.**
- **3.3 Evaluation integrity.** The `test_patch` timing question. SWE-bench standard: apply post-agent. Our original (Apr 2026) harness: applied pre-agent — a leak. Issue #226 closed the `git diff` vector; Issue #287 (May 2026) closed the `cat tests/` vector by deferring `apply_test_patch` to post-agent. **Disclosure: numbers in this paper are post-#287; pre-#287 numbers are not comparable and have been archived.**
- **3.4 The Capability Overlap framing.** Zhang et al.'s tool-use-tax inequality reframed for coding tools. IDE primitive capability ⊆ bash capability for Read/Grep/Glob/Write — these are "tax without grip" on tasks where bash alone suffices. Edit is the one IDE primitive with non-overlapping capability (atomic byte-precise replace with lint). Bash's *capability* is task-invariant; its *cost in turns* depends on whether the agent can explore the workspace efficiently.
- **3.5 Dual cost reporting (methodology).** [**TODO prose:** the section opens by stating two facts that constrain how cost can honestly be reported.

  - **Fact 1 — No documented cache-isolation mechanism.** Across all four surfaces this paper touches — the Anthropic Messages API, the Claude Code CLI, the OpenAI Responses API, and the OpenAI Codex CLI — **there is no documented way to isolate the prompt cache, or any other server-side token-caching mechanism the vendor operates, within a session or prevent other sessions from reusing tokens cached by an earlier session.** The claim extends beyond the "prompt cache" label specifically: we surveyed the documentation for any cached-tokens primitive (prompt-prefix cache, conversation-state persistence, stored responses, server-side context retention, automatic KV reuse) and found no parameter, flag, environment variable, or namespace knob that forces a cache miss, scopes cached tokens to a single caller, or prevents cross-session reuse. The only documented mechanism is implicit: change the cached content so the cache key changes. Sources to cite (URLs included for human verification — **do not auto-insert into `references.bib`**; await approval per repo policy):
    - **Anthropic Messages API prompt caching.** `cache_control` enables a cache breakpoint; the documentation describes no inverse parameter (no `skip`, no namespace, no `cache_key` analogue). Cache scope is "Organization" by default with no per-session opt-out. URL: `https://docs.claude.com/en/docs/build-with-claude/prompt-caching`.
    - **Anthropic context-editing (other server-side cached tokens).** Context editing is a server-side compaction-class primitive that retains and reshapes state across turns; the documentation describes lifecycle and scope but exposes no per-session isolation knob. URL: `https://platform.claude.com/docs/en/build-with-claude/context-editing` (canonical; `docs.claude.com/...` 302-redirects here).
    - **Claude Code CLI.** The CLI reference, settings.json reference, and environment-variable list contain no `--no-cache`, `--cache-key`, or `--fresh-session` flag. The closest existing flag, `--no-session-persistence`, controls only local session state, not the upstream API cache. URLs: `https://docs.claude.com/en/docs/claude-code/cli-reference`, `https://docs.claude.com/en/docs/claude-code/settings`.
    - **OpenAI Responses API prompt caching.** Caching is documented as automatic with no opt-out. The `prompt_cache_key` parameter is a **routing / partition hint** combined with the prefix hash for cache lookup, not a disable switch — and crucially not a security boundary, so other sessions can still hit the same cache when prefixes collide. URL: `https://platform.openai.com/docs/guides/prompt-caching`.
    - **OpenAI Responses API stored state (other server-side cached tokens).** `store=true` paired with `previous_response_id` retains conversation tokens server-side for later reuse across requests; the only documented opt-out is `store=false`, which disables retention entirely rather than scoping it to a session. *[TODO: confirm canonical URL — `platform.openai.com/docs/api-reference/responses` returned 403 in agent-side WebFetch; verify manually before `.bib` insertion.]*
    - **OpenAI Codex CLI.** The README and configuration documentation expose no cache flag or environment variable. URL: `https://github.com/openai/codex` (verify against the README at the commit hash cited in §4 once the agent-version table is finalized).
  - **Fact 2 — Custom isolation attempts are not reliably effective.** We implemented two: a per-task tool-name nonce in codex's `tools[]` array (issue #294, worked empirically), and the symmetric mechanism via a stub MCP server for Claude Code (issue #296). A 3-task back-to-back smoke test of #296 on `tool_rich` artifact tasks showed the iso pass's first task hitting Anthropic's cache identically to a contaminated task — Claude Code reported the stub MCP server as `status: pending` in the session-init record, so the nonced tool never landed in the outbound `tools[]` array before the first API call. The failure mode is invisible to unit tests (argv shape is correct) and is a property of agent runtime we don't control. Empirically reliable cache isolation across both providers is therefore not on offer with the harness we have.

  Given those two facts, every cost figure in §5 is reported under two accounting models side-by-side:

  - **(a) Token-based cost** = `input_tokens × full_input_rate + output_tokens × output_rate`. Charged at non-cached rates throughout. Depends only on agent behavior on each task; reproducible from raw `turn.completed.usage` JSONL records; immune to provider cache-state variation. Functions as a deterministic upper bound on what a fresh-cache user would pay.
  - **(b) Cache-adjusted cost.** Charges the per-arm shared prefix (system prompt + tool definitions, byte-identical across tasks in an arm) at the **cache-read rate** for *every* task, including the task that happened to prime the cache. Concretely: let `X` = first-turn `cache_read_input_tokens` on the median non-primer task in an arm; move `X` tokens of every task's first-turn `cache_creation` into `cache_read` for accounting purposes. Within-task multi-turn cache reads (turns ≥ 2) are unchanged. The result is a steady-state cost: what each task would cost in a world where the shared prefix is always warm — independent of who happened to run first in our experiment. Removes the run-order asymmetry without claiming we achieved isolation.

  - **Why both.** Token-based isolates agent behavior from infrastructure but ignores caching entirely (the upper bound). Cache-adjusted reflects deployment economics (steady-state pricing) without leaking run-order into the comparison. A user's real cost sits between the two depending on workload locality. The *gap* between the two columns is itself a finding — it varies by arm (different shared-prefix sizes) and quantifies how much caching matters for each arm's cost profile.

  - **What to emphasize in the prose.** Token-based is the primary metric for cross-arm comparisons (no caching noise). Cache-adjusted is reported alongside to ground the comparison in something a deployer would actually pay. We explicitly do *not* report raw observed cost (the API-billed amount), because the smoke test in Fact 2 shows it is sensitive to run order and to ambient cache state we cannot control — and because reporting numbers we know are confounded would mislead readers.

  - **Open OpenAI bugs that contribute to the problem** (cite in prose): codex#20301 (gpt-5.5 cache rate), codex#5556 (ChatGPT-login auth degraded caching), codex#19996 (cache-warming init call). These reinforce Fact 1: even when caching is documented at the API level, behavior in practice is undocumented and non-stationary.

  - **Length target.** 5–7 sentences in the final prose. The bracketed text above is the guide; condense aggressively when writing.]

---

## 4. Experimental Setup (0.5 page target; 0.75 ceiling)

- **Benchmarks.**
  - **artifact suite:** 93 tasks across 9 categories (algorithmic, data_engineering, data_processing, data_science, enumeration, iterative_numerical, ml_engineering, stateful_reasoning, verification_heavy). Hidden deterministic graders, offline, seeded-random only. Covers the (computation, single+multi-file) regime cell.
  - **SWE-bench Mini:** 100 instances split as verified-mini (Django 25 + Sphinx 25) and datasci-mini (sklearn 15 + matplotlib 12 + xarray 8 + sympy 7 + seaborn 5 + astropy 3). Covers (modification, multi-file). Standard post-agent `test_patch` protocol.
- **Agent surfaces.**
  - Claude Code (claude-sonnet-4-6, version 2.1.139). Three arms × the IDE tool surface ablation.
  - Codex CLI (gpt-5.5). Reported as generalization probe in §5.
- **Arms.** Mapped per harness: artifact uses `tool_rich`/`bash_only`/`code_only`; SWE-bench uses `baseline`/`bash_only`/`onlycode` (same semantics, legacy naming).
- **Seeds.** Three independent runs per (instance, arm) — `runs/swebench/full_run_seed_{1,2,3}/` and `runs/artifact/full_run_seed_{1,2,3}/`. Mean ± stderr over seeds reported in main tables.
- **Metrics.** Pass rate (PASS / (PASS + FAIL); env_fail excluded), total cost (USD), total turns, median per-instance cost. Per-turn cost as a secondary diagnostic.
- **Excluded.** `env_fail` instances (pre-flight `pytest --collect-only` returns zero items) excluded from pass-rate denominators per Issue #238; reported separately.

---

## 5. Main Results (2.0 page target; 2.25 ceiling)

Numbers freeze before this section is written. Until then, table/figure slots are reserved but blank.

- **5.1 Headline table.** Per-arm pass rate, total cost (**both token-based AND cache-adjusted — two cost columns side by side per §3.5**), median per-instance cost, turns, $/turn — split by regime (artifact / SWE-bench), with 95% CI from seed variance.
- **5.2 Sign-flip figure (Figure 1).** Cost ratio `code_only / tool_rich` per regime, two bars: artifact `<1.0` (code_only cheaper), SWE-bench `>1.0` (tool_rich cheaper). The single visual that defends contribution bullet #1.
- **5.3 Capability invariance.** Pass-rate table by arm × regime, showing ≤2pp spread within each regime. Defends contribution bullet #2.
- **5.4 Per-repo breakdown (SWE-bench).** Django/Sphinx vs sklearn/matplotlib/xarray/sympy/seaborn/astropy. Where the modification-regime sign-flip is most/least pronounced.
- **5.5 Agreement matrix.** Where the arms disagree on pass/fail. Most instances unanimous; signal lives in 6-or-so split instances per repo.
- **5.6 Generalization to Codex CLI.** 1-paragraph note: Codex's bash-first prompt design flips the SWE-bench ranking (code_only cheaper than tool_rich). Implication: optimal surface is jointly determined by regime AND agent design.

---

## 6. The Redundancy Table — Table 1 (0.5 page target; 0.75 ceiling)

Lifted from issue #158:

| Claude Code primitive | Bash equivalent | Capability beyond bash? |
|---|---|---|
| Read | `cat`, `head`, `tail`, `sed -n` | Bounded output, line numbering — UX, not capability |
| Grep | `grep -rn`, `rg` | None |
| Glob | `find`, `ls **/` | None |
| Edit | `sed -i`, `patch`, heredoc | **Yes — atomic byte-precise replace with lint** |
| Write | `cat > file <<EOF` | None |
| Bash | (itself) | — |

Lead the section: *"Five of six IDE primitives are bash subsets in capability. The sign-flip in §5 means the redundant tools nevertheless earn their token budget on the modification regime — by saving exploration turns, not by adding capability."*

---

## 7. Discussion (0.5 page target; 0.75 ceiling)

- **Why the sign-flip exists.** Capability Overlap on computation tasks → IDE tools are pure overhead. On modification + exploration tasks, IDE tools save *turns* (better recall over code structure), offsetting the per-turn tax. Per-turn cost ranking (`tool_rich > code_only ≈ bash_only`) holds in both regimes; only the turn-count ranking flips.
- **Where the method works / doesn't.** Section is a 4-paragraph honest accounting; update after numbers freeze.
- **Implications for agent design.** Workshop audience expects actionable claims — a one-paragraph guideline like *"if your tasks are computation-dominated, drop the IDE surface; if modification-dominated, keep Edit at minimum."* Hold drafting until §5 numbers are final.

---

## 8. Limitations (0.25 page target; 0.5 ceiling — required by ACM template, desk-reject if missing)

- Two agent surfaces only (Claude Code, Codex CLI). No GPT-5 or Gemini 2.5.
- Sample size: 93 artifact + 100 SWE-bench instances. Statistical power for the sign-flip is high (22pp gap); per-cell SWE-bench breakdowns are noisier.
- `test_patch` is applied post-agent (standard SWE-bench protocol); pre-#287 legacy data is not comparable and is omitted.
- 12 SWE-bench instances (sympy + mwaskom) hit auth-failures in seed_1 and were re-run; documented in appendix.

---

## 9. Ethics Statement (optional)

Likely skip — no human subjects, no closed-model API misuse. Decide after the draft is whole.

---

## File map for `paper/`

Each section below should eventually have its own outline file (top-level `.md`) plus prose file (`sections/*.tex`). Naming convention: `NN_section_name.md` (outline) + `sections/NN_section_name.tex` (prose).

| File | Status | Owner |
|---|---|---|
| `outline.md` | ✅ this file | — |
| `figures_outline.md` | ✅ scaffolded | — |
| `00_abstract.md` | pending | freeze last |
| `01_introduction.md` | pending | day 1 |
| `02_related_work.md` | ✅ materialized (was `related_work.md`) | maintain |
| `03_method.md` | pending | day 2 |
| `04_experimental_setup.md` | pending | day 2 |
| `05_results.md` | pending | day 3 (after numbers freeze) |
| `06_redundancy_table.md` | pending | day 3 |
| `07_discussion.md` | pending | day 4 |
| `99_limitations.md` | pending | day 4 |
| `sections/*.tex` | pending | day 5 — prose |
| `main.tex` | ✅ scaffolded (acmart) | — |
| `macros.tex` | ✅ ported from hallulens | — |
| `references.bib` | pending — populate from `02_related_work.md` | day 4 |
| `build_numbers.py` | ✅ ported | — |
| `lint.py` | ✅ ported | — |
| `Makefile` | ✅ ported | — |
| `data/` | pending — first CSV after numbers freeze | day 3 |
| `figures_src/` | pending | day 3 |

---

## Numbers-freeze gate

Tables and figures in §5–§7 cannot be drafted until the post-#287 seed runs complete:

- ✅ artifact seed_1 (Claude) — 93 tasks
- ✅ SWE-bench seed_1 (Claude) — 88 valid instances (auth recovery for 12 in progress)
- ✅ SWE-bench seed_1 (Codex) — 100 instances
- 🟡 SWE-bench seed_2/3 (Claude) — in progress
- 🟡 SWE-bench seed_2/3 (Codex) — in progress
- 🟡 artifact seed_1 (Codex) — just started; seeds 2/3 not started

**Sign-flip is detectable from seed_1 alone (22pp magnitude vs ~1–2pp seed noise expected).** Variance bands from seeds 2/3 are needed for the headline table, not for the qualitative claim.

---

## Methodology decisions log

Standing decisions on harness configuration for the seed runs that feed §5. Append-only.

- **2026-05-26 — Dual cost reporting (cache-independent AND observed).** Every cost figure in §5 will be reported in two columns side by side:
  - **Cache-independent** = `input × full_rate + output × output_rate` — depends only on token counts, model-deterministic, reproducible from existing JSONL records, immune to OpenAI cache-state variation.
  - **Observed (with-cache)** = `(input − cached) × full_rate + cached × cache_rate + output × output_rate` — reflects the actual API billing during our runs; non-deterministic across reruns due to OpenAI cache non-stationarity.
  Rationale: empirical 4-run sequential smoke tests on three code_only artifact tasks showed the same task's `cached_input_tokens` swing from 0 → 17,920 → 8,704 → 16,896 with no harness change, driven entirely by OpenAI's non-stationary prompt cache and cross-account/cross-process cache pollution. Neither view alone is faithful: cache-independent is methodologically clean but inflates absolute cost vs real deployments; observed reflects what we paid but is unreproducible. Reporting both makes the methodology honest and lets readers see the *gap* (= cache savings) which is itself a finding — it differs by arm and reflects how well each arm's prefix overlaps with ambient workloads on the same OpenAI account. Open OpenAI bugs that contribute to the observed-cost non-stationarity and motivated this dual choice: codex#20301 (gpt-5.5 cache rate), codex#5556 (ChatGPT-login auth caching), codex#19996 (cache-warming init call). **Must be documented in §3.5 of the method section, in the headline table caption of §5.1, and referenced in the Limitations bullet on cost measurement. §7 Discussion should also note the per-arm cache-savings gap as a secondary finding.**
- **2026-05-26 (superseded above) — Option A "cache isolation = ON" was the prior tentative decision.** Rolled back in favor of dual reporting; cache isolation requires re-running every (instance, arm, run, seed) triple, while dual reporting can derive both columns from existing JSONL records. The `--cache-isolation` harness flag is retained for possible follow-up work but is **not** used for paper headline numbers.
- **2026-05-26 (refines dual-reporting entry above) — Second cost column is "cache-adjusted", not "raw observed".** The original dual-reporting decision proposed reporting *raw* API-billed cost as the with-cache column. A subsequent empirical check on Claude — issue #296's symmetric cache-isolation implementation, smoke-tested on 3 sequential `tool_rich` artifact tasks — found that (a) the no-iso pass replicates the cross-task contamination signature (~9871 tokens of first-turn `cache_read` on tasks 2 and 3, primer task at 0), and (b) the iso pass fails to break the cache because Claude Code reports the stub MCP server as `status: pending` at session init and the nonced tool never reaches the outbound `tools[]` array before the first API call (`tool_count=28` and no `iso_nonce` strings in any of 3 iso-pass JSONLs). Codex #294 worked; Claude #296 does not. Reporting raw observed cost would therefore leak run-order asymmetry into the comparison whenever the harness can't reliably force a miss. The refined methodology reports **token-based** (charge everything at non-cached rates) and **cache-adjusted** (charge the shared per-arm prefix at the cache-read rate for every task, including the primer — formula in §3.5) instead of raw observed. This yields two run-order-independent numbers, the first an upper bound, the second a steady-state estimate. Open questions deferred: which cost is the "true" deployment number is workload-dependent; the paper reports both and lets the reader pick.

---

## Backup venue

If KDD June 1 slips, **[SE 3.0 — Agentic Software Engineering Workshop at KDD 2026](https://agent-se.github.io/)** is a likely deadline-extension fallback (same conference, more coding-agent-focused audience). **[NeurIPS 2026 workshops](https://neurips.cc/)** (CFPs announced ~July 11, deadlines ~Aug 29) is the realistic backup with 8–12 more weeks of polish.
