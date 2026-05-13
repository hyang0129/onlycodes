"""Hidden grader for ``data_science__iqr_anomaly_flagging_easy``.

Recomputes the Tukey 1.5×IQR outlier set from
``scratch_dir/measurements.csv`` and compares the agent's
``output/result.json`` field-by-field. All-or-nothing scoring.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


INPUT_CSV = "measurements.csv"
OUTPUT_REL = "output/result.json"
REQUIRED_FIELDS = {"flagged_ids"}
IQR_FACTOR = 1.5


def _compute_expected(scratch_dir: Path) -> list[int]:
    df = pd.read_csv(scratch_dir / INPUT_CSV)
    values = df["value"].to_numpy()
    q1 = float(np.quantile(values, 0.25))
    q3 = float(np.quantile(values, 0.75))
    iqr = q3 - q1
    lo = q1 - IQR_FACTOR * iqr
    hi = q3 + IQR_FACTOR * iqr
    mask = (values < lo) | (values > hi)
    return sorted(int(x) for x in df.loc[mask, "id"].tolist())


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

    fids = data["flagged_ids"]
    if not isinstance(fids, list) or not all(
        isinstance(x, int) and not isinstance(x, bool) for x in fids
    ):
        return GradeResult(False, 0.0, "flagged_ids must be a list of integers")
    if fids != sorted(fids):
        return GradeResult(False, 0.0, "flagged_ids must be sorted in ascending order")
    if len(set(fids)) != len(fids):
        return GradeResult(False, 0.0, "flagged_ids contains duplicates")

    expected = _compute_expected(scratch_dir)

    if set(fids) != set(expected):
        got = set(fids)
        ref = set(expected)
        missing_ids = sorted(ref - got)
        extra_ids = sorted(got - ref)
        bits: list[str] = []
        if missing_ids:
            bits.append(f"{len(missing_ids)} outlier id(s) missing")
        if extra_ids:
            bits.append(
                f"{len(extra_ids)} non-outlier id(s) incorrectly flagged"
            )
        return GradeResult(
            False,
            0.0,
            "flagged_ids does not match the Tukey 1.5×IQR rule: "
            + "; ".join(bits)
            + " (check: Q1/Q3 via linear-interpolation quantile, "
              "fence = [Q1 - 1.5*IQR, Q3 + 1.5*IQR], compare on the "
              "value column, return the id column)",
        )

    return GradeResult(
        True,
        1.0,
        f"identified {len(expected)} outlier(s) under Tukey 1.5×IQR rule",
    )
