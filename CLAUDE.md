# onlycodes

Benchmark testing whether Claude Code performs better when restricted to writing/executing code vs. using native file-system tools.

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

- Venv lives **outside** the overlay (sibling dir). After each mount, `pip install -e .` is re-run to regenerate `.egg-info` (which was scrubbed from the cached lowerdir).
- Lockfile drift (agent leaked a pip install) triggers full cache entry rebuild, not a skip.

### Artifact no-leak invariant

`grader/hidden.py` and `reference_output.*` must never appear in the agent's scratch dir. `materialize()` enforces this via a post-copy scan and raises `MaterializationError` on violation. This is a pre-flight check — catch it before the run, not after.

### Grader subprocess isolation

`_artifact_grade_runner.py` is the grader entry point. It runs in a fresh subprocess so grader-side exceptions don't kill the harness. Grade results are serialized as JSON on stdout; do not add logging to stdout in grader code.

### Execution budget is declared, not enforced

`max_code_runs` and `max_wall_seconds` in task.yaml are reserved fields. Enforcement is always OFF in seed-v1; the harness logs "enforcement OFF (0 = unlimited)".

### Claude invocation is always isolated

`run_claude()` creates a temp config dir containing only `.credentials.json` + `.claude.json` and sets `CLAUDE_CONFIG_DIR` to it. Always uses `--dangerously-skip-permissions --no-session-persistence`. Never shares state between arms or runs.

### Tool restriction for onlycode / code_only

The onlycode arm passes `--tools mcp__codebox__execute_code,mcp__codebox__execute_code_and_wait` and `--disallowedTools` covering all built-in tools. This is implemented in `run.py`; check there before modifying tool lists.

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
