# onlycodes

Benchmark testing whether Claude Code performs better when restricted to writing/executing code vs. using native file-system tools.

## Paper Writing

The KDD 2026 Agentic AI Evaluation Workshop paper draft lives in [paper/](paper/). **When writing the paper, only reference files inside `paper/`, unless the user explicitly names a source outside it.** This applies to drafting, editing, or extending sections, outline, abstract, claims, tables, figures, and bibliography — and covers reading, citing, comparing against, or otherwise consulting external files, not just copying prose from them.

Concretely: do not read `docs/ROADMAP.md`, `docs/RESULTS_SWE_MINI.md`, `docs/CATEGORY_*.md`, `README.md`, or any other location outside `paper/` when working on paper content. The old "Code Mode hypothesis" framing in those files is **superseded** by the regime-dependent sign-flip finding documented in [issue #158 comment 2026-05-25](https://github.com/hyang0129/onlycodes/issues/158); reading them risks pulling stale framing into the draft. If a fact, number, or framing from outside `paper/` needs to land in the draft, the user will name the source explicitly.

The single source of truth for numbers cited in the paper is `paper/data/*.csv` and `paper/generated/figures/*.numbers.csv`, accessed through the `\result`/`\resdelta`/`\resratio`/`\resultCI`/`\resultPM` macros defined in `paper/macros.tex`. See `paper/README.md` for the build pipeline. **A stale value is a build failure (via `paper/lint.py`), not a proofreading task.**

**Never edit `paper/references.bib` directly** — add citations in the relevant outline/section file with enough context for a human to verify, and wait for explicit human approval before any `.bib` insertion (agents hallucinate references).

**The `analyze/` pathology pipeline is OUT of paper scope (decided 2026-05-28).** The harness ships a three-stage analysis pipeline — mechanical extractor → Claude-classifier subagents → synthesizer → `patterns.json` — documented below in the **Module Map** (rows for `analyze/*.py`) and in the **Analysis Sidecar Layout** section. **None of its output lands in the paper.** No failure-mode taxonomy, no mechanical-flag distributions, no subagent-classified findings, no `patterns.json` reference, no per-instance pattern hits — not in §3 (Method), §4 (Experimental Setup), §5 (Results), §6 (Discussion), or §7 (Limitations). The paper's full metric surface is pass rate + cache-adjusted cost + input/output tokens; nothing else. Rationale (story-completeness, page budget, classifier-defense methodology debt), surface-effect audit list, and future-agent guardrails live in [paper/outline.md](paper/outline.md)'s Methodology decisions log entry dated 2026-05-28 — read that entry before reopening the decision. **The pipeline itself is not deprecated**: it remains valid harness instrumentation for debugging and follow-up work; the exclusion is paper-scope only. **If a paper-writing agent encounters `analyze/`-related code, sidecar JSON, or `patterns.json` content during research, treat it the same as `docs/ROADMAP.md`: out of scope, do not import, do not cite, do not summarize into the draft.**

**Target venue:** [Agentic Software Engineering (SE 3.0) Workshop at KDD 2026](https://agent-se.github.io/) — submission deadline **2026-06-01 AOE**, **8 pages excl. references** (long paper), ACM KDD template (`\documentclass[sigconf,anonymous,review]{acmart}`), double-blind, non-archival. **Venue switched 2026-05-27** from the KDD 2026 Workshop on Evaluation and Trustworthiness of Agentic AI (now backup venue — same June 1 deadline, 9-page ceiling, same ACM template family). SE 3.0 hits four direct topic axes (Agent Tool Use & Environments, Failure Modes & Root Causes, Economic Cost & Impact, Trustworthiness & Reliability) vs. one for the prior venue, and the reviewer pool is coding-agent researchers rather than monitoring/governance. Cost is one page off the ceiling (9 → 8). Full rationale in [paper/outline.md](paper/outline.md) header and [paper/README.md](paper/README.md) "Submission target" section.

### Overleaf sync (subtree split)

The `paper/` directory is mirrored to a standalone repo, [`hyang0129/onlycodes-paper`](https://github.com/hyang0129/onlycodes-paper), which Overleaf imports as a project. The mirror exists because Overleaf's GitHub import struggles with the full `onlycodes` repo's size. The remote is configured as `paper` (alongside `origin`) in this clone.

**Sync workflow (run from `onlycodes/` repo root):**

```sh
# Push local paper/ edits out to onlycodes-paper → Overleaf pulls
git subtree push --prefix=paper paper main

# Pull Overleaf edits back into paper/ as a merge commit
git subtree pull --prefix=paper paper main --squash
```

Always `git subtree pull` before editing `paper/` locally if Overleaf may have changes; otherwise you'll get divergent histories. After pulling, the merge commit lands on `main`.

**Caveats:**
- **`paper/lint.py` does NOT run on Overleaf.** A stale `\result{...}` macro value is a build failure locally (CLAUDE.md guarantee above) but renders silently on Overleaf. Re-run `make` locally before treating any Overleaf-rendered PDF as authoritative.
- **The mirror repo is public.** Fine for editing; before submitting to the double-blind venue, scrub the PDF's author metadata and ensure no Overleaf/GitHub URL is embedded.
- **Subtree split rewrites commit SHAs.** A commit in `onlycodes` has a different hash in `onlycodes-paper`. Don't cherry-pick across the two repos by SHA.

## Architecture Overview

Two independent evaluation modes sharing a common subprocess harness:

```
swebench.cli (python -m swebench)
  ├── add          → fetch HuggingFace instances → problems/swe/<set>/<id>.yaml
  ├── run          → SWE-bench: baseline vs onlycode arms on real repos
  ├── analyze      → pathology pipeline (3 stages) + summary table
  ├── cache        → OverlayFS instance cache lifecycle
  └── artifact run → artifact-graded: code_only vs tool_rich on YAML tasks

Shared infrastructure:
  harness.py   — git ops, venv setup, claude invocation, test running
  cache.py     — OverlayFS backend, lockfile, scrub
```

**Full CLI reference:** see README.md. **Task schema:** see docs/SCHEMA_ARTIFACT.md.

---

## Module Map

| Module | Owns |
|---|---|
| `cli.py` | Click group wiring only; no logic |
| `models.py` | `Problem`, `ArmResult` — SWE-bench data classes |
| `add.py` | HuggingFace fetch, repo validation, YAML write |
| `run.py` | SWE-bench arm orchestration, overlay refresh, parallel scheduling |
| `harness.py` | `clone_repo`, `setup_venv`, `strip_git_history`, `run_claude`, `run_tests`, `apply_test_patch` |
| `cache.py` | OverlayFS mount/unmount, lockfile verify, scrub |
| `cache_cli.py` | `cache setup` / `cache clean` CLI |
| `artifact_models.py` | `Task`, `ExecutionBudget`, `GradeResult`, `ArtifactArmResult` — disjoint from SWE-bench models |
| `artifact_loader.py` | Walk `problems/artifact/`, parse task.yaml, validate schema |
| `artifact_materialize.py` | Copy workspace → scratch, run generator, enforce no-leak |
| `artifact_grade.py` | Invoke `grader/hidden.py:grade()` in subprocess, parse JSON |
| `_artifact_grade_runner.py` | Subprocess entry point for grader; do not call directly |
| `artifact_run.py` | Artifact arm orchestration (materialize → run_claude → grade) |
| `artifact_cli.py` | `artifact run` / `artifact verify` CLI |
| `analyze/run.py` | 3-stage pathology pipeline; writes sidecar JSON + patterns.json |
| `analyze/compress.py` | Compress JSONL for subagent input |
| `analyze/extractor.py` | Mechanical pattern detection (loops, OOM, timeout, syntax errors) |
| `analyze/registry.py` | Load/merge/write patterns.json |
| `analyze/summary.py` | Flat results table (pass rate, cost, turns) |

**Arm naming:** SWE-bench uses `baseline` / `onlycode`; artifact uses `tool_rich` / `code_only`.

---

## Key Invariants

Violating any of these breaks benchmark integrity or sandbox isolation.

### Git history stripping is mandatory

`strip_git_history()` collapses the repo to a single orphan commit, then deletes all refs, packed-refs, reflogs, and runs `git gc --prune=now`. The agent must not recover the reference fix via `git log`.

- **`git_reset()` resets to `"HEAD"` (the orphan), not `base_commit`** — `base_commit` is unreachable after stripping.
- Called in every non-cached setup path and in `_refresh_overlay()` between arms.
- Uses fixed author date so re-stripping produces the same orphan SHA (idempotent).

### Overlay refresh, not git reset, between arms

fuse-overlayfs copy-up semantics prevent `git clean -fd` from un-creating files added during a run (EEXIST). Between arms, `_refresh_overlay()` unmounts → deletes upper+work dirs → recreates → remounts → re-strips history. The merged path stays the same.

- With `--venv-isolation` (default on): the venv is also overlaid per-arm — see "Per-arm venv overlay" below.
- With `--no-venv-isolation` (legacy): the venv lives as a shared sibling dir. After each mount, `pip install -e .` is re-run to regenerate `.egg-info`. Lockfile drift (agent leaked a pip install) triggers full cache entry rebuild.

### Per-arm venv overlay (`--venv-isolation`)

The cached venv at `instances/<id>/venv/` (formerly a shared mutable dir) is now a per-arm fuse-overlayfs mountpoint when `--venv-isolation` is on (default).

**Layout:** `cache setup` builds the venv at `instances/<id>/venv/` (shebangs bake to this path), then renames it to `instances/<id>/venv_lower/`, leaving `venv/` free as the mountpoint. Legacy entries with only `venv/` are lazily migrated (`venv/ → venv_lower/`) on first isolated run.

**Shebang invariant (non-negotiable):** The fuse-overlayfs mount MUST be at the original venv creation path (`venv/`). Because console scripts bake `#!<abs-path>/venv/bin/python` at creation time, any other mount path breaks every `pip` / `pytest` invocation. Never mount the overlay at a per-arm tempdir.

**Arms are serialised within an instance.** Intra-instance parallelism is not supported — if it is added later, this per-arm-overlay design requires a shebang-relocation solution and a separate merged path per arm.

**Drift detection under isolation:** `verify_lockfile` on `venv_lower/` is a paranoia assertion — agent pip-installs cannot reach `venv_lower/` through the overlay. A drift hit here means the overlay logic itself broke; log loudly and rebuild.

**Cleanup on exception:** `venv_overlay()` is a context manager with `try/finally`. Orphan mounts are the existing pain point; do not add code paths that bypass the `finally` block.

### Artifact no-leak invariant

`grader/hidden.py` and `reference_output.*` must never appear in the agent's scratch dir. `materialize()` enforces this via a post-copy scan and raises `MaterializationError` on violation. This is a pre-flight check — catch it before the run, not after.

### Grader subprocess isolation

`_artifact_grade_runner.py` is the grader entry point. It runs in a fresh subprocess so grader-side exceptions don't kill the harness. Grade results are serialized as JSON on stdout; do not add logging to stdout in grader code.

### Execution budget is declared, not enforced

`max_code_runs` and `max_wall_seconds` in task.yaml are reserved fields. Enforcement is always OFF in seed-v1; the harness logs "enforcement OFF (0 = unlimited)".

### Claude invocation is always isolated

`run_claude()` creates a temp config dir containing only `.credentials.json` + `.claude.json` and sets `CLAUDE_CONFIG_DIR` to it. Always uses `--dangerously-skip-permissions --no-session-persistence`. Never shares state between arms or runs.

### Tool restriction for onlycode / code_only

The onlycode arm passes `--tools mcp__codebox__execute_code,mcp__codebox__list_tools` and `--disallowedTools` covering all built-in tools. This is implemented in `runner.py:ClaudeRunner.build_tools_flags`; check there before modifying tool lists.

### patterns.json is append-only during runs

`analyze/registry.py` merges new pattern IDs into `patterns.json` (append), never overwrites existing entries. Tests are guarded by an autouse fixture (`tests/conftest.py:_patterns_json_is_immutable`) that fails if patterns.json is modified. Edit by hand only to remove stale entries.

---

## Test Conventions

```
tests/
  conftest.py              — autouse: snapshot patterns.json before/after each test
  test_cache.py            — unit: overlay, lockfile, scrub
  test_cache_integration.py — @integration: real clone + real overlay mount
  test_harness_strip.py    — git history stripping (single orphan, no reflog)
  test_artifact_loader.py  — schema parse + validation
  test_artifact_materialize.py — copytree + no-leak invariant
  test_artifact_run.py     — end-to-end arm execution (stubbed run_claude)
  test_artifact_grade.py   — grader subprocess pass/fail/exception
  test_artifact_cli.py     — CLI integration
  test_verify_graders.py   — reference output matches grader
  test_analyze_*.py        — pathology pipeline stages
  test_run.py              — SWE-bench run integration
```

- Mark slow/network tests with `@pytest.mark.integration`.
- Skip integration tests: `pytest -m "not integration"`.
- Monkeypatch `SWEBENCH_CACHE_ROOT` in fixtures — never touch the real cache in tests.
- Use `--runs 1 --parallel 1` in test invocations to keep logs deterministic.

---

## Config Files

**`mcp-config.json`** — MCP server config for the codebox (execute_code) tool. Sets `ONLYCODES_PERSISTENT_KERNEL=1` to enable a persistent Python REPL across calls. The harness strips this env var for `--no-persistent-kernel` runs by writing a modified config to a temp file.

**`exec_server/passthrough-config.json`** — Interception rules for the MCP bridge (sub-MCP-manager). Defines content and dispatch deny-lists without code changes. Add rules here to block tool calls or patterns in execute_code output.

**`exec_server/`** — Self-contained MCP exec-server stack: JS runtime (`exec-server.js`, `bridge-server.js`, `config-loader.js`, `interceptor.js`, `sub-mcp-manager.js`), Python kernel helpers (`codebox.py`, `mcp_bridge.py`, `python_kernel.py`), config (`passthrough-config.json`), and build (`build.mjs`). Python helpers live alongside the JS because `exec-server.js` stages them into the execute_code scratch dir via `__dirname`. `npm run build` emits `exec_server/dist/exec-server.bundle.mjs` (gitignored).

---

## Artifact Task Authoring

Tasks live under `problems/artifact/<category>/<slug>/`. Required layout:

```
task.yaml               # fields: instance_id, category, difficulty, problem_statement,
                        #   workspace_dir, output_artifact, hidden_grader,
                        #   reference_output, execution_budget
workspace/              # public files copied into agent scratch dir
grader/
  hidden.py             # grade(scratch_dir) → GradeResult; must be deterministic + offline
  reference_output.*    # reference artifact for grader validation
```

Grader invariants: deterministic, offline, seeded-random only. `grade()` must not write to `scratch_dir`. Score is a float in [0.0, 1.0]. See `docs/SCHEMA_ARTIFACT.md` for the full contract.

Instance ID format: `<category>__<slug>` (two underscores). Category must match the directory name.

---

## Analysis Sidecar Layout

> **Harness instrumentation only — does NOT feed the paper.** See the *Paper Writing* section above (2026-05-28 decision). The pipeline still runs and is still useful for debugging and follow-up work; it is just outside the scope of the current draft.

```
runs/swebench/_analysis/<run_id>/
  mechanical/          # Stage 1: JSON per JSONL log (mechanical flags + metrics)
  subagents/           # Stage 2: JSON per flagged log (Claude-classified findings)
  synthesizer.json     # Stage 3: full synthesizer output before merge into patterns.json
```

---

## Legacy Scripts

`scripts/run_prevalidation.sh`, `scripts/run_mcp_integration_test.sh` — original fixture-based benchmarks (5-task suite in `data/fixtures/`). Still valid as a fast smoke test.

`scripts/run_swebench.sh` — earlier shell-based SWE-bench runner (single instance, hardcoded problem text). Superseded by `python -m swebench run` but retained as a reference.
