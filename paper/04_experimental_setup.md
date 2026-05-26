# 04 — Experimental Setup

**Target length:** 0.5 page (ceiling 0.75). Tight — push details to appendix if needed.

## Benchmarks

### Artifact suite (computation regime)

- **n = 93 tasks** across 9 categories: `algorithmic`, `data_engineering`, `data_processing`, `data_science`, `enumeration`, `iterative_numerical`, `ml_engineering`, `stateful_reasoning`, `verification_heavy`.
- Each task defines: `workspace/` (public files copied to agent scratch dir), `grader/hidden.py` (deterministic offline grade function), `reference_output.*` (canonical artifact for grader validation). Hidden grader runs in an isolated subprocess via `_artifact_grade_runner.py`.
- **Grader invariants:** deterministic, offline, seeded-random only. `grade(scratch_dir)` returns a float in [0.0, 1.0]; passes at ≥0.5 (per-task threshold may vary).
- **No-leak invariant:** `materialize()` enforces a post-copy scan that `grader/hidden.py` and `reference_output.*` never appear in the agent's scratch dir. Violation raises `MaterializationError` pre-flight.
- **Regime cell:** (computation, single-file) for most tasks; (computation, multi-file) for the `data_engineering` (n=15) and `ml_engineering` (n=15) categories.

### SWE-bench Mini (modification regime)

- **n = 100 instances** sampled from SWE-bench Verified, split as:
  - `swebench-verified-mini`: 50 instances — Django (25) + Sphinx (25). Standard web-framework code.
  - `swebench-datasci-mini`: 50 instances — scikit-learn (15), matplotlib (12), xarray (8), sympy (7), seaborn (5), astropy (3). Scientific Python.
- Evaluation: standard post-agent `test_patch` protocol (see §3.3) — `apply_test_patch` runs after the agent finishes; `run_tests` then executes the instance's `test_cmd`.
- **Regime cell:** (modification, multi-file) for all 100 instances.

## Agent surfaces

| Surface | Model | Version | Role |
|---|---|---|---|
| Claude Code | claude-sonnet-4-6 | 2.1.139 | Primary — all three arms |
| Codex CLI | gpt-5.5 | latest at run time | Secondary — generalization probe (§5.6) |

The Codex CLI port mirrors the Claude Code three-arm semantics: `tool_rich` = full Codex tool surface, `bash_only` = bash-only via Codex's tool-restriction flags, `code_only` = single `execute_code` MCP tool. See [`runner.py`](../swebench/runner.py) for the per-surface flag construction (commit `27815b8` ensures `tool_rich/bash_only` arms mirror Claude semantics).

## Arms

Per harness convention, arm names differ between benchmarks:

| Conceptual arm | Artifact name | SWE-bench name |
|---|---|---|
| Full IDE surface | `tool_rich` | `baseline` |
| Bash only | `bash_only` | `bash_only` |
| Single MCP execute_code | `code_only` | `onlycode` |

The semantics are identical; the naming is legacy. We unify under the conceptual names in prose and tables.

## Seeds

- **Three independent seeds** per (instance, arm): `runs/{swebench,artifact}/full_run_seed_{1,2,3}/` for Claude; `..._codex/` for Codex.
- **Seed independence:** each seed has its own `--output-dir`; no cross-contamination. `--resume` (default on) skips any `(instance, arm, run)` triple with a completed result, so re-running a partial batch is safe within a seed.
- **Variance reporting:** mean ± stderr across seeds in the main results table; per-seed values in the appendix.

## Metrics

Primary:
- **Pass rate** = PASS / (PASS + FAIL). `env_fail` instances (pre-flight `pytest --collect-only` returns zero items per [Issue #238](https://github.com/hyang0129/onlycodes/issues/238)) excluded from denominator and reported separately.
- **Total cost (USD)** — sum across non-env_fail runs per arm. Cost from Claude API usage telemetry; Codex cost estimated from token usage per [Issue #253](https://github.com/hyang0129/onlycodes/issues/253).
- **Median per-instance cost** — robust against outliers (a few timeout-budget instances skew totals significantly).
- **Total turns** — sum of agent turns across non-env_fail runs.

Secondary:
- **Per-turn cost** = total cost / total turns. Diagnostic for separating "per-turn tax" from "turn count efficiency."
- **Wall time** — reported in the appendix.

## Compute budget

Estimated total compute for the post-#287 reruns:
- Claude SWE-bench: 100 inst × 3 arms × 3 seeds ≈ $300 + ~$50 retry overhead from auth-failed recovery.
- Codex SWE-bench: 100 inst × 3 arms × 3 seeds ≈ $600 (Codex per-token cost is higher than Claude).
- Artifact (Claude + Codex): 93 tasks × 3 arms × 3 seeds × 2 surfaces ≈ $200.

**Reported runs in this paper come from `runs/{swebench,artifact}/full_run_seed_{1,2,3}{,_codex}/` only.** Legacy pre-#287 data in `runs/swebench/_legacy_pre_287/` is archived for protocol-comparison reference but not reported.

## Excluded

- **Pre-#287 SWE-bench runs** — not comparable due to the integrity bug fixed in §3.3.
- **Codex on artifact** seeds 2/3 — auth recovery + scheduling means these may not complete before the June 1 deadline; if missing, footnoted in §5.6.
- **Instances with venv build failures** — small set of tail instances where the cached venv requires manual interventions (`pip install -e .` egg-info, lockfile drift); listed in appendix.
