"""Hidden grader for ml_engineering__curve_queries_{easy,medium,hard}.

Uses pandas to recompute reference answers from ``experiments.csv`` in
``scratch_dir``, then checks the agent's ``output/answers.json`` query by
query with partial credit.

    score = correct_queries / total_queries
    passed = (score == 1.0)

Difficulty is inferred from steps_per_run = len(df) // 50:

  easy   (≤2 000 steps/run) — 1 query  → score ∈ {0.0, 1.0}
  medium (≤20 000)          — 3 queries → score ∈ {0, 0.33, 0.67, 1.0}
  hard   (>20 000)          — 5 queries → score ∈ {0, 0.2, 0.4, 0.6, 0.8, 1.0}

Per-query checks:
  best_val_loss_per_run    — dict {run_id: float}, all 50 keys, within FLOAT_TOL
  convergence_step_per_run — dict {run_id: int},   all 50 keys, exact integer
  mean_train_val_gap       — float scalar, within FLOAT_TOL
  overfit_onset_per_run    — dict {run_id: int},   all 50 keys, exact integer
  best_run_overall         — string, exact match

Pandas is justified here (not stdlib csv) because experiments.csv is up to
2M rows / ~100MB. Recomputing via pure-Python csv would dominate grade time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

EXPERIMENTS_REL = "experiments.csv"
OUTPUT_REL = "output/answers.json"
FLOAT_TOL = 1e-3
N_RUNS = 50


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


def _difficulty(steps_per_run: int) -> str:
    if steps_per_run <= 2_000:
        return "easy"
    if steps_per_run <= 20_000:
        return "medium"
    return "hard"


_QUERIES: dict[str, list[str]] = {
    "easy":   ["best_val_loss_per_run"],
    "medium": ["best_val_loss_per_run", "convergence_step_per_run", "mean_train_val_gap"],
    "hard":   ["best_val_loss_per_run", "convergence_step_per_run", "mean_train_val_gap",
               "overfit_onset_per_run", "best_run_overall"],
}


def _compute_expected(df: pd.DataFrame, queries: list[str]) -> dict:
    expected: dict = {}

    # Always compute per-run best (needed for Q2, Q4, Q5 thresholds).
    per_run_best = df.groupby("run_id", sort=False)["val_loss"].min()

    if "best_val_loss_per_run" in queries:
        expected["best_val_loss_per_run"] = per_run_best.to_dict()

    if "convergence_step_per_run" in queries:
        result: dict[str, int] = {}
        for run_id, group in df.groupby("run_id", sort=False):
            thresh = per_run_best[run_id] * 1.05
            mask = group["val_loss"].values <= thresh
            if mask.any():
                first_pos = int(mask.argmax())
                result[run_id] = int(group["step"].iloc[first_pos])
            else:
                result[run_id] = -1
        expected["convergence_step_per_run"] = result

    if "mean_train_val_gap" in queries:
        expected["mean_train_val_gap"] = float((df["val_loss"] - df["train_loss"]).mean())

    if "overfit_onset_per_run" in queries:
        result2: dict[str, int] = {}
        for run_id, group in df.groupby("run_id", sort=False):
            thresh = per_run_best[run_id] * 1.10
            vals = group["val_loss"].values
            # First occurrence of minimum val_loss (iloc index within group).
            best_iloc = int(vals.argmin())
            # Rows strictly after the best step.
            after = vals[best_iloc + 1:]
            after_steps = group["step"].values[best_iloc + 1:]
            mask2 = after > thresh
            if mask2.any():
                result2[run_id] = int(after_steps[int(mask2.argmax())])
            else:
                result2[run_id] = -1
        expected["overfit_onset_per_run"] = result2

    if "best_run_overall" in queries:
        expected["best_run_overall"] = str(per_run_best.idxmin())

    return expected


def _check_dict_float(agent_val: object, ref: dict[str, float], key: str) -> str | None:
    """Return error string or None if pass."""
    if not isinstance(agent_val, dict):
        return f"{key}: expected dict, got {type(agent_val).__name__}"
    missing = sorted(set(ref) - set(agent_val))[:3]
    extra = sorted(set(agent_val) - set(ref))[:3]
    if missing:
        return f"{key}: missing run_ids {missing}"
    if extra:
        return f"{key}: unexpected run_ids {extra}"
    for run_id, ref_v in ref.items():
        agent_v = agent_val[run_id]
        if not isinstance(agent_v, (int, float)):
            return f"{key}[{run_id}]: expected float, got {type(agent_v).__name__}"
        if abs(float(agent_v) - ref_v) > FLOAT_TOL:
            return f"{key}[{run_id}]: got {agent_v}, expected {ref_v:.6f} (diff > {FLOAT_TOL})"
    return None


def _check_dict_int(agent_val: object, ref: dict[str, int], key: str) -> str | None:
    if not isinstance(agent_val, dict):
        return f"{key}: expected dict, got {type(agent_val).__name__}"
    missing = sorted(set(ref) - set(agent_val))[:3]
    extra = sorted(set(agent_val) - set(ref))[:3]
    if missing:
        return f"{key}: missing run_ids {missing}"
    if extra:
        return f"{key}: unexpected run_ids {extra}"
    for run_id, ref_v in ref.items():
        agent_v = agent_val[run_id]
        if isinstance(agent_v, bool) or not isinstance(agent_v, int):
            return f"{key}[{run_id}]: expected int, got {type(agent_v).__name__}"
        if agent_v != ref_v:
            return f"{key}[{run_id}]: got {agent_v}, expected {ref_v}"
    return None


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()

    csv_path = scratch_dir / EXPERIMENTS_REL
    if not csv_path.is_file():
        return GradeResult(False, 0.0, f"input {EXPERIMENTS_REL} not found in scratch dir")

    output_path = scratch_dir / OUTPUT_REL
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact output/answers.json not produced")

    try:
        agent_out = json.loads(output_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse output/answers.json: {exc}")

    if not isinstance(agent_out, dict):
        return GradeResult(False, 0.0, "output/answers.json must be a JSON object")

    try:
        df = pd.read_csv(
            csv_path,
            dtype={"step": int, "run_id": str, "train_loss": float, "val_loss": float, "lr": float},
        )
    except Exception as exc:
        return GradeResult(False, 0.0, f"could not read experiments.csv: {exc}")

    total_rows = len(df)
    steps_per_run = total_rows // N_RUNS
    diff = _difficulty(steps_per_run)
    queries = _QUERIES[diff]

    expected = _compute_expected(df, queries)

    results: list[tuple[str, bool, str]] = []   # (query, passed, detail)

    for q in queries:
        ref = expected[q]
        agent_v = agent_out.get(q)

        if agent_v is None:
            results.append((q, False, f"{q}: key missing from output"))
            continue

        if q == "best_val_loss_per_run":
            err = _check_dict_float(agent_v, ref, q)
        elif q == "convergence_step_per_run":
            err = _check_dict_int(agent_v, ref, q)
        elif q == "mean_train_val_gap":
            if not isinstance(agent_v, (int, float)):
                err = f"{q}: expected float scalar, got {type(agent_v).__name__}"
            elif abs(float(agent_v) - ref) > FLOAT_TOL:
                err = f"{q}: got {agent_v}, expected {ref:.6f} (diff > {FLOAT_TOL})"
            else:
                err = None
        elif q == "overfit_onset_per_run":
            err = _check_dict_int(agent_v, ref, q)
        elif q == "best_run_overall":
            if not isinstance(agent_v, str):
                err = f"{q}: expected string, got {type(agent_v).__name__}"
            elif agent_v != ref:
                err = f"{q}: got {agent_v!r}, expected {ref!r}"
            else:
                err = None
        else:
            err = f"unknown query {q!r}"

        if err is None:
            results.append((q, True, f"{q}: correct"))
        else:
            results.append((q, False, err))

    n_correct = sum(1 for _, ok, _ in results if ok)
    n_total = len(queries)
    score = n_correct / n_total
    passed = n_correct == n_total

    detail_parts = [f"{q}: {'OK' if ok else 'FAIL — ' + msg}" for q, ok, msg in results]
    detail = f"[{diff}] {n_correct}/{n_total} queries correct; " + "; ".join(detail_parts)

    return GradeResult(passed=passed, score=round(score, 6), detail=detail)
