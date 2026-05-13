"""Hidden grader for ``data_science__twogroup_ttest_easy``.

Recomputes Welch's two-sample t-test from ``scratch_dir/measurements.csv``
and compares the agent's ``output/result.json`` field-by-field. All-or-
nothing scoring.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


INPUT_CSV = "measurements.csv"
OUTPUT_REL = "output/result.json"
ALPHA = 0.05
STAT_TOL = 1e-4
PVAL_TOL = 1e-6
MEAN_TOL = 1e-4
REQUIRED_INT_FIELDS = {"n_control", "n_treatment"}
REQUIRED_FLOAT_FIELDS = {"mean_control", "mean_treatment", "statistic", "pvalue"}
REQUIRED_BOOL_FIELDS = {"reject_null"}
REQUIRED_FIELDS = REQUIRED_INT_FIELDS | REQUIRED_FLOAT_FIELDS | REQUIRED_BOOL_FIELDS


def _compute_expected(scratch_dir: Path) -> dict:
    df = pd.read_csv(scratch_dir / INPUT_CSV)
    control = df.loc[df["group"] == "control", "value"].to_numpy()
    treatment = df.loc[df["group"] == "treatment", "value"].to_numpy()
    res = stats.ttest_ind(treatment, control, equal_var=False, alternative="two-sided")
    return {
        "n_control": int(len(control)),
        "n_treatment": int(len(treatment)),
        "mean_control": float(np.mean(control)),
        "mean_treatment": float(np.mean(treatment)),
        "statistic": float(res.statistic),
        "pvalue": float(res.pvalue),
        "reject_null": bool(float(res.pvalue) < ALPHA),
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

    for f in REQUIRED_INT_FIELDS:
        if not isinstance(data[f], int) or isinstance(data[f], bool):
            return GradeResult(
                False, 0.0, f"{f} must be a non-bool integer; got {type(data[f]).__name__}"
            )
    for f in REQUIRED_FLOAT_FIELDS:
        v = data[f]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return GradeResult(
                False, 0.0, f"{f} must be a number; got {type(v).__name__}"
            )
    if not isinstance(data["reject_null"], bool):
        return GradeResult(
            False,
            0.0,
            f"reject_null must be a boolean; got {type(data['reject_null']).__name__}",
        )

    expected = _compute_expected(scratch_dir)

    if data["n_control"] != expected["n_control"]:
        return GradeResult(
            False,
            0.0,
            f"n_control mismatch: got {data['n_control']}, "
            f"expected {expected['n_control']} (count of rows where group=='control')",
        )
    if data["n_treatment"] != expected["n_treatment"]:
        return GradeResult(
            False,
            0.0,
            f"n_treatment mismatch: got {data['n_treatment']}, "
            f"expected {expected['n_treatment']} (count of rows where group=='treatment')",
        )
    for f, tol in (
        ("mean_control", MEAN_TOL),
        ("mean_treatment", MEAN_TOL),
        ("statistic", STAT_TOL),
        ("pvalue", PVAL_TOL),
    ):
        if abs(float(data[f]) - expected[f]) > tol:
            hint = ""
            if f == "statistic":
                hint = (
                    " (check: ttest_ind(treatment, control, equal_var=False) — "
                    "treatment is the FIRST argument; sign is positive when "
                    "treatment mean > control mean)"
                )
            return GradeResult(
                False,
                0.0,
                f"{f} off by more than {tol} from the canonical value{hint}",
            )
    if bool(data["reject_null"]) != expected["reject_null"]:
        return GradeResult(
            False,
            0.0,
            f"reject_null mismatch: got {data['reject_null']}, "
            f"expected {expected['reject_null']} (rule: pvalue < {ALPHA})",
        )

    return GradeResult(
        True,
        1.0,
        f"Welch's t={expected['statistic']:.4f}, p={expected['pvalue']:.3e}, "
        f"reject_null={expected['reject_null']}",
    )
