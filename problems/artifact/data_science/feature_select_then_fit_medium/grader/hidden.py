"""Hidden grader for ``data_science__feature_select_then_fit_medium``.

Recomputes the correlation-based feature selection → LinearRegression →
in-sample RMSE pipeline from ``scratch_dir/signals.csv`` and compares the
agent's ``output/result.json`` field-by-field. All-or-nothing scoring.
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


INPUT_CSV = "signals.csv"
OUTPUT_REL = "output/result.json"
FEATURE_COLS = [f"x{i}" for i in range(1, 11)]
TARGET_COL = "y"
REQUIRED_FIELDS = {"selected_features", "rmse"}
ALLOWED_FEATURES = set(FEATURE_COLS)
CORR_THRESHOLD = 0.30
RMSE_TOL = 1e-4


def _compute_expected(scratch_dir: Path) -> dict:
    df = pd.read_csv(scratch_dir / INPUT_CSV)
    y = df[TARGET_COL].to_numpy()

    # Pearson correlation of each feature with y, computed via the unbiased
    # estimator (pandas/numpy default).
    selected: list[str] = []
    for col in FEATURE_COLS:
        r = float(np.corrcoef(df[col].to_numpy(), y)[0, 1])
        if abs(r) >= CORR_THRESHOLD:
            selected.append(col)
    selected.sort()  # lexicographic; e.g. ['x1', 'x3', 'x5', 'x7']

    X_sel = df[selected].to_numpy()
    model = LinearRegression()
    model.fit(X_sel, y)
    y_pred = model.predict(X_sel)

    rmse = float(math.sqrt(float(np.mean((y_pred - y) ** 2))))
    return {"selected_features": selected, "rmse": rmse}


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

    sf = data["selected_features"]
    if not isinstance(sf, list) or not all(isinstance(x, str) for x in sf):
        return GradeResult(False, 0.0, "selected_features must be a list of strings")
    bad = [x for x in sf if x not in ALLOWED_FEATURES]
    if bad:
        return GradeResult(
            False, 0.0, f"selected_features contains unknown names: {bad}"
        )
    if sf != sorted(sf):
        return GradeResult(
            False,
            0.0,
            "selected_features must be sorted in ascending lexicographic order",
        )
    if len(set(sf)) != len(sf):
        return GradeResult(False, 0.0, "selected_features contains duplicates")

    if not isinstance(data["rmse"], (int, float)) or isinstance(data["rmse"], bool):
        return GradeResult(
            False, 0.0, f"rmse must be a number; got {type(data['rmse']).__name__}"
        )

    expected = _compute_expected(scratch_dir)

    expected_set = set(expected["selected_features"])
    got_set = set(sf)
    if got_set != expected_set:
        missing = sorted(expected_set - got_set)
        unexpected = sorted(got_set - expected_set)
        bits: list[str] = []
        if missing:
            bits.append(f"{len(missing)} feature(s) under the |r|≥{CORR_THRESHOLD} threshold not selected")
        if unexpected:
            bits.append(f"{len(unexpected)} feature(s) under the threshold incorrectly selected")
        return GradeResult(
            False,
            0.0,
            "selected_features does not match the threshold rule: " + "; ".join(bits),
        )
    if abs(float(data["rmse"]) - expected["rmse"]) > RMSE_TOL:
        return GradeResult(
            False,
            0.0,
            f"rmse off by more than {RMSE_TOL} from the pipeline value "
            "(check: Pearson |r|≥0.30 selection on x1..x10, default LinearRegression "
            "fit on selected features only, in-sample RMSE)",
        )

    return GradeResult(
        True,
        1.0,
        f"selected {len(expected['selected_features'])} feature(s) above |r|≥{CORR_THRESHOLD}; "
        "in-sample RMSE within tolerance",
    )
