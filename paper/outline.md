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
- **3.2 Harness design.** Subprocess isolation (`run_claude` creates temp `CLAUDE_CONFIG_DIR`), per-arm overlay refresh (fuse-overlayfs upper+work reset between arms), per-instance venv (outside overlay), git-history strip (single orphan commit, no reflog, no `base_commit` recoverability).
- **3.3 Evaluation integrity.** The `test_patch` timing question. SWE-bench standard: apply post-agent. Our original (Apr 2026) harness: applied pre-agent — a leak. Issue #226 closed the `git diff` vector; Issue #287 (May 2026) closed the `cat tests/` vector by deferring `apply_test_patch` to post-agent. **Disclosure: numbers in this paper are post-#287; pre-#287 numbers are not comparable and have been archived.**
- **3.4 The Capability Overlap framing.** Zhang et al.'s tool-use-tax inequality reframed for coding tools. IDE primitive capability ⊆ bash capability for Read/Grep/Glob/Write — these are "tax without grip" on tasks where bash alone suffices. Edit is the one IDE primitive with non-overlapping capability (atomic byte-precise replace with lint). Bash's *capability* is task-invariant; its *cost in turns* depends on whether the agent can explore the workspace efficiently.

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

- **5.1 Headline table.** Per-arm pass rate, total cost, median per-instance cost, turns, $/turn — split by regime (artifact / SWE-bench), with 95% CI from seed variance.
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

## Backup venue

If KDD June 1 slips, **[SE 3.0 — Agentic Software Engineering Workshop at KDD 2026](https://agent-se.github.io/)** is a likely deadline-extension fallback (same conference, more coding-agent-focused audience). **[NeurIPS 2026 workshops](https://neurips.cc/)** (CFPs announced ~July 11, deadlines ~Aug 29) is the realistic backup with 8–12 more weeks of polish.
