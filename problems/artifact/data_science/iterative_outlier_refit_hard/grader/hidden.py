"""Hidden grader for ``data_science__iterative_outlier_refit_hard``.

Recomputes the iterative outlier-refit pipeline from
``scratch_dir/data.csv`` and compares the agent's ``output/result.json``
field-by-field. All-or-nothing scoring.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


INPUT_CSV = "data.csv"
OUTPUT_REL = "output/result.json"
FEATURE_COLS = ["x1", "x2", "x3"]
TARGET_COL = "y"
REQUIRED_FIELDS = {
    "outlier_indices",
    "n_iterations",
    "final_intercept",
    "final_coefficients",
    "final_rmse",
}
Z_THRESHOLD = 3.0
MAX_ITER = 50
FLOAT_TOL = 1e-4


def _run_pipeline(scratch_dir: Path) -> dict:
    df = pd.read_csv(scratch_dir / INPUT_CSV)
    X_all = df[FEATURE_COLS].to_numpy()
    y_all = df[TARGET_COL].to_numpy()
    n = len(df)

    included = set(range(n))
    prev_outliers: set[int] | None = None
    iteration = 0
    last_model: LinearRegression | None = None
    last_included: set[int] | None = None

    while iteration < MAX_ITER:
        iteration += 1
        idx = sorted(included)
        X_fit = X_all[idx]
        y_fit = y_all[idx]
        model = LinearRegression()
        model.fit(X_fit, y_fit)

        y_hat = model.predict(X_all)
        residuals = y_all - y_hat
        sigma = float(np.std(residuals[idx], ddof=0))
        # sigma > 0 is guaranteed for this dataset; defensive guard.
        if sigma == 0.0:
            raise RuntimeError("residual std collapsed to zero — degenerate data")
        z = residuals / sigma
        current_outliers = {i for i in range(n) if abs(float(z[i])) > Z_THRESHOLD}

        last_model = model
        last_included = set(included)

        if prev_outliers is not None and current_outliers == prev_outliers:
            break

        prev_outliers = current_outliers
        included = set(range(n)) - current_outliers
    else:
        raise RuntimeError(
            f"iterative outlier loop failed to converge within {MAX_ITER} iterations"
        )

    assert last_model is not None and last_included is not None
    idx = sorted(last_included)
    y_pred_inliers = last_model.predict(X_all[idx])
    rmse = float(math.sqrt(float(np.mean((y_pred_inliers - y_all[idx]) ** 2))))

    return {
        "outlier_indices": sorted(current_outliers),
        "n_iterations": iteration,
        "final_intercept": float(last_model.intercept_),
        "final_coefficients": [float(c) for c in last_model.coef_],
        "final_rmse": rmse,
    }


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    output_path = scratch_dir / OUTPUT_REL

    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        data = json.loads(output_path.read_text())
    except json.JSONDecodeError as exc:
        return GradeResult(False, 0.0, f"output is not valid JSON: {exc}")

    if not isinstance(data, dict):
        return GradeResult(
            False, 0.0, f"top-level JSON must be an object; got {type(data).__name__}"
        )

    keys = set(data.keys())
    missing = REQUIRED_FIELDS - keys
    extra = keys - REQUIRED_FIELDS
    if missing:
        return GradeResult(False, 0.0, f"missing required field(s): {sorted(missing)}")
    if extra:
        return GradeResult(False, 0.0, f"unexpected extra field(s): {sorted(extra)}")

    oi = data["outlier_indices"]
    if not isinstance(oi, list) or not all(
        isinstance(x, int) and not isinstance(x, bool) for x in oi
    ):
        return GradeResult(False, 0.0, "outlier_indices must be a list of integers")
    if oi != sorted(oi):
        return GradeResult(
            False, 0.0, "outlier_indices must be sorted in ascending order"
        )
    if len(set(oi)) != len(oi):
        return GradeResult(False, 0.0, "outlier_indices contains duplicates")

    n_it = data["n_iterations"]
    if not isinstance(n_it, int) or isinstance(n_it, bool):
        return GradeResult(
            False, 0.0, f"n_iterations must be an integer; got {type(n_it).__name__}"
        )

    fi = data["final_intercept"]
    if not isinstance(fi, (int, float)) or isinstance(fi, bool):
        return GradeResult(
            False, 0.0, f"final_intercept must be a number; got {type(fi).__name__}"
        )

    fc = data["final_coefficients"]
    if (
        not isinstance(fc, list)
        or len(fc) != len(FEATURE_COLS)
        or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in fc)
    ):
        return GradeResult(
            False,
            0.0,
            f"final_coefficients must be a list of exactly {len(FEATURE_COLS)} numbers",
        )

    fr = data["final_rmse"]
    if not isinstance(fr, (int, float)) or isinstance(fr, bool):
        return GradeResult(
            False, 0.0, f"final_rmse must be a number; got {type(fr).__name__}"
        )

    try:
        expected = _run_pipeline(scratch_dir)
    except Exception as exc:
        return GradeResult(False, 0.0, f"reference pipeline failed: {exc}")

    if set(oi) != set(expected["outlier_indices"]):
        got = set(oi)
        ref = set(expected["outlier_indices"])
        missing_idx = sorted(ref - got)
        extra_idx = sorted(got - ref)
        bits: list[str] = []
        if missing_idx:
            bits.append(f"{len(missing_idx)} reference outlier(s) missing")
        if extra_idx:
            bits.append(f"{len(extra_idx)} non-outlier(s) incorrectly flagged")
        return GradeResult(
            False,
            0.0,
            "outlier_indices does not match the converged set: " + "; ".join(bits),
        )

    if n_it != expected["n_iterations"]:
        return GradeResult(
            False,
            0.0,
            f"n_iterations mismatch: got {n_it}, expected {expected['n_iterations']} "
            "(check: comparison starts at iteration 2, sigma uses ddof=0 on included "
            "rows only, threshold is strict abs(z) > 3.0)",
        )

    if abs(float(fi) - expected["final_intercept"]) > FLOAT_TOL:
        return GradeResult(
            False,
            0.0,
            f"final_intercept off by more than {FLOAT_TOL} from the final fit's "
            "intercept on the inlier rows",
        )

    for j, (got_c, ref_c) in enumerate(zip(fc, expected["final_coefficients"])):
        if abs(float(got_c) - ref_c) > FLOAT_TOL:
            return GradeResult(
                False,
                0.0,
                f"final_coefficients[{j}] (column {FEATURE_COLS[j]}) off by more "
                f"than {FLOAT_TOL} from the final fit's coefficient on inlier rows "
                "(check: feature column order is [x1, x2, x3])",
            )

    if abs(float(fr) - expected["final_rmse"]) > FLOAT_TOL:
        return GradeResult(
            False,
            0.0,
            f"final_rmse off by more than {FLOAT_TOL} from the in-sample RMSE of "
            "the final fit on the inlier rows",
        )

    return GradeResult(
        True,
        1.0,
        f"converged in {expected['n_iterations']} iteration(s) with "
        f"{len(expected['outlier_indices'])} outlier(s); final fit within tolerance",
    )
