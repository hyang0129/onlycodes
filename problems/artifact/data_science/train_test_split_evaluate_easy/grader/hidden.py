"""Hidden grader for ``data_science__train_test_split_evaluate_easy``.

Recomputes the train_test_split → LinearRegression → RMSE pipeline from
``scratch_dir/housing.csv`` and compares the agent's ``output/result.json``
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
from sklearn.model_selection import train_test_split


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


INPUT_CSV = "housing.csv"
OUTPUT_REL = "output/result.json"
FEATURE_COLS = ["x1", "x2", "x3", "x4", "x5"]
TARGET_COL = "y"
REQUIRED_FIELDS = {"rmse", "n_train", "n_test"}
RMSE_TOL = 1e-4


def _compute_expected(scratch_dir: Path) -> dict:
    df = pd.read_csv(scratch_dir / INPUT_CSV)
    X = df[FEATURE_COLS].to_numpy()
    y = df[TARGET_COL].to_numpy()

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, shuffle=True
    )

    model = LinearRegression()
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)

    rmse = float(math.sqrt(float(np.mean((y_pred - y_test) ** 2))))
    return {
        "rmse": rmse,
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
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

    # Type checks (mirror the structural verifier).
    if not isinstance(data["rmse"], (int, float)) or isinstance(data["rmse"], bool):
        return GradeResult(
            False, 0.0, f"rmse must be a number; got {type(data['rmse']).__name__}"
        )
    if not isinstance(data["n_train"], int) or isinstance(data["n_train"], bool):
        return GradeResult(
            False,
            0.0,
            f"n_train must be a non-bool integer; got {type(data['n_train']).__name__}",
        )
    if not isinstance(data["n_test"], int) or isinstance(data["n_test"], bool):
        return GradeResult(
            False,
            0.0,
            f"n_test must be a non-bool integer; got {type(data['n_test']).__name__}",
        )

    expected = _compute_expected(scratch_dir)

    if data["n_train"] != expected["n_train"]:
        return GradeResult(
            False,
            0.0,
            f"n_train ({data['n_train']}) does not match the canonical 80/20 "
            "split with random_state=42",
        )
    if data["n_test"] != expected["n_test"]:
        return GradeResult(
            False,
            0.0,
            f"n_test ({data['n_test']}) does not match the canonical 80/20 "
            "split with random_state=42",
        )
    if abs(float(data["rmse"]) - expected["rmse"]) > RMSE_TOL:
        return GradeResult(
            False,
            0.0,
            f"rmse off by more than {RMSE_TOL} from the pipeline value "
            "(check: 80/20 split with random_state=42, default LinearRegression, "
            "RMSE = sqrt(mean((y_pred - y_test)**2)))",
        )

    return GradeResult(
        True,
        1.0,
        "pipeline matches canonical split + LinearRegression fit + RMSE",
    )
