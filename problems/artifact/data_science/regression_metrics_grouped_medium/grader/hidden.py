"""Hidden grader for ``data_science__regression_metrics_grouped_medium``.

Recomputes per-group and overall RMSE/MAE/R² from
``scratch_dir/predictions.csv`` and compares the agent's
``output/result.json`` field-by-field. All-or-nothing scoring.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, r2_score


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


INPUT_CSV = "predictions.csv"
OUTPUT_REL = "output/result.json"
REQUIRED_TOP = {"per_group", "overall"}
REQUIRED_GROUP_FIELDS = {"group", "n", "rmse", "mae", "r2"}
REQUIRED_OVERALL_FIELDS = {"n", "rmse", "mae", "r2"}
FLOAT_TOL = 1e-4


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    return {
        "n": int(len(y_true)),
        "rmse": float(math.sqrt(float(np.mean((y_pred - y_true) ** 2)))),
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "r2": float(r2_score(y_true, y_pred)),
    }


def _compute_expected(scratch_dir: Path) -> dict:
    df = pd.read_csv(scratch_dir / INPUT_CSV)
    per_group = []
    for name, sub in df.groupby("group", sort=True):
        m = _metrics(sub["y_true"].to_numpy(), sub["y_pred"].to_numpy())
        per_group.append({"group": str(name), **m})
    overall = _metrics(df["y_true"].to_numpy(), df["y_pred"].to_numpy())
    return {"per_group": per_group, "overall": overall}


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
    missing = REQUIRED_TOP - keys
    extra = keys - REQUIRED_TOP
    if missing:
        return GradeResult(False, 0.0, f"missing top-level field(s): {sorted(missing)}")
    if extra:
        return GradeResult(False, 0.0, f"unexpected top-level field(s): {sorted(extra)}")

    pg = data["per_group"]
    if not isinstance(pg, list):
        return GradeResult(False, 0.0, "per_group must be a list")
    for i, entry in enumerate(pg):
        if not isinstance(entry, dict):
            return GradeResult(False, 0.0, f"per_group[{i}] must be an object")
        ek = set(entry.keys())
        if ek != REQUIRED_GROUP_FIELDS:
            return GradeResult(
                False,
                0.0,
                f"per_group[{i}] keys {sorted(ek)} != {sorted(REQUIRED_GROUP_FIELDS)}",
            )
        if not isinstance(entry["group"], str):
            return GradeResult(False, 0.0, f"per_group[{i}].group must be a string")
        if not isinstance(entry["n"], int) or isinstance(entry["n"], bool):
            return GradeResult(
                False, 0.0, f"per_group[{i}].n must be a non-bool integer"
            )
        for fld in ("rmse", "mae", "r2"):
            v = entry[fld]
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                return GradeResult(
                    False, 0.0, f"per_group[{i}].{fld} must be a number"
                )

    names = [e["group"] for e in pg]
    if names != sorted(names):
        return GradeResult(
            False, 0.0, "per_group must be sorted ascending by group name"
        )
    if len(set(names)) != len(names):
        return GradeResult(False, 0.0, "per_group has duplicate group names")

    ov = data["overall"]
    if not isinstance(ov, dict):
        return GradeResult(False, 0.0, "overall must be an object")
    ok_keys = set(ov.keys())
    if ok_keys != REQUIRED_OVERALL_FIELDS:
        return GradeResult(
            False,
            0.0,
            f"overall keys {sorted(ok_keys)} != {sorted(REQUIRED_OVERALL_FIELDS)}",
        )
    if not isinstance(ov["n"], int) or isinstance(ov["n"], bool):
        return GradeResult(False, 0.0, "overall.n must be a non-bool integer")
    for fld in ("rmse", "mae", "r2"):
        v = ov[fld]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return GradeResult(False, 0.0, f"overall.{fld} must be a number")

    expected = _compute_expected(scratch_dir)

    exp_names = [e["group"] for e in expected["per_group"]]
    if names != exp_names:
        got = set(names)
        ref = set(exp_names)
        missing_g = sorted(ref - got)
        extra_g = sorted(got - ref)
        bits: list[str] = []
        if missing_g:
            bits.append(f"missing group(s): {missing_g}")
        if extra_g:
            bits.append(f"unexpected group(s): {extra_g}")
        if not bits:
            bits.append("group order differs (must be ascending lexicographic)")
        return GradeResult(False, 0.0, "per_group group set mismatch: " + "; ".join(bits))

    for got_entry, exp_entry in zip(pg, expected["per_group"]):
        gname = exp_entry["group"]
        if got_entry["n"] != exp_entry["n"]:
            return GradeResult(
                False,
                0.0,
                f"per_group[{gname}].n mismatch: got {got_entry['n']}, "
                f"expected {exp_entry['n']}",
            )
        for fld in ("rmse", "mae", "r2"):
            if abs(float(got_entry[fld]) - exp_entry[fld]) > FLOAT_TOL:
                return GradeResult(
                    False,
                    0.0,
                    f"per_group[{gname}].{fld} off by more than {FLOAT_TOL} "
                    "from the canonical per-group value "
                    "(check: r2_score uses the per-group mean of y_true; "
                    "rmse = sqrt(mean(sq_err)); mae = mean(abs_err))",
                )

    if ov["n"] != expected["overall"]["n"]:
        return GradeResult(
            False,
            0.0,
            f"overall.n mismatch: got {ov['n']}, expected {expected['overall']['n']}",
        )
    for fld in ("rmse", "mae", "r2"):
        if abs(float(ov[fld]) - expected["overall"][fld]) > FLOAT_TOL:
            return GradeResult(
                False,
                0.0,
                f"overall.{fld} off by more than {FLOAT_TOL} from the pooled "
                "(all-rows-concatenated) value",
            )

    return GradeResult(
        True,
        1.0,
        f"per-group ({len(pg)}) and overall RMSE/MAE/R² all within ±{FLOAT_TOL}",
    )
