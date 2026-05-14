"""Hidden grader for ``data_science__classification_metrics_easy``.

Recomputes accuracy, precision, recall, and F1 from
``scratch_dir/predictions.csv`` and compares the agent's
``output/result.json`` field-by-field. All-or-nothing scoring.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
)


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


INPUT_CSV = "predictions.csv"
OUTPUT_REL = "output/result.json"
REQUIRED_FIELDS = {"accuracy", "precision", "recall", "f1"}
FLOAT_TOL = 1e-4


def _compute_expected(scratch_dir: Path) -> dict:
    df = pd.read_csv(scratch_dir / INPUT_CSV)
    y_true = df["y_true"].to_numpy()
    y_pred = df["y_pred"].to_numpy()
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, pos_label=1)),
        "recall": float(recall_score(y_true, y_pred, pos_label=1)),
        "f1": float(f1_score(y_true, y_pred, pos_label=1)),
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

    for field in REQUIRED_FIELDS:
        v = data[field]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return GradeResult(
                False, 0.0, f"{field} must be a number; got {type(v).__name__}"
            )

    expected = _compute_expected(scratch_dir)

    for field in ("accuracy", "precision", "recall", "f1"):
        if abs(float(data[field]) - expected[field]) > FLOAT_TOL:
            return GradeResult(
                False,
                0.0,
                f"{field} off by more than {FLOAT_TOL} from the canonical value "
                "(check: pos_label=1, hard predictions, standard binary "
                "TP/FP/FN/TN definitions)",
            )

    return GradeResult(
        True,
        1.0,
        f"all four binary metrics within ±{FLOAT_TOL} of canonical values",
    )
