"""Hidden grader for ``data_science__cohort_ttest_medium``.

Recomputes the paired t-test per cohort and pooled from
``scratch_dir/pairs.csv`` and compares the agent's
``output/result.json`` field-by-field. All-or-nothing scoring.
"""

from __future__ import annotations

import json
import math
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


INPUT_CSV = "pairs.csv"
OUTPUT_REL = "output/result.json"
ALPHA = 0.05
STAT_TOL = 1e-4
MEAN_TOL = 1e-4
PVAL_REL_TOL = 1e-3
PVAL_ABS_TOL = 1e-15
REQUIRED_TOP = {"per_cohort", "overall"}
REQUIRED_COHORT_FIELDS = {
    "cohort", "n_pairs", "mean_diff", "statistic", "pvalue", "reject_null",
}
REQUIRED_OVERALL_FIELDS = {
    "n_pairs", "mean_diff", "statistic", "pvalue", "reject_null",
}


def _scope_result(before: np.ndarray, after: np.ndarray) -> dict:
    res = stats.ttest_rel(after, before, alternative="two-sided")
    diffs = after - before
    return {
        "n_pairs": int(len(diffs)),
        "mean_diff": float(np.mean(diffs)),
        "statistic": float(res.statistic),
        "pvalue": float(res.pvalue),
        "reject_null": bool(float(res.pvalue) < ALPHA),
    }


def _compute_expected(scratch_dir: Path) -> dict:
    df = pd.read_csv(scratch_dir / INPUT_CSV)
    per_cohort = []
    for name, sub in df.groupby("cohort", sort=True):
        b = sub["before"].to_numpy()
        a = sub["after"].to_numpy()
        entry = {"cohort": str(name)}
        entry.update(_scope_result(b, a))
        per_cohort.append(entry)
    overall = _scope_result(df["before"].to_numpy(), df["after"].to_numpy())
    return {"per_cohort": per_cohort, "overall": overall}


def _pval_close(got: float, ref: float) -> bool:
    return math.isclose(got, ref, rel_tol=PVAL_REL_TOL, abs_tol=PVAL_ABS_TOL)


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

    pc = data["per_cohort"]
    if not isinstance(pc, list):
        return GradeResult(False, 0.0, "per_cohort must be a list")
    for i, entry in enumerate(pc):
        if not isinstance(entry, dict):
            return GradeResult(False, 0.0, f"per_cohort[{i}] must be an object")
        ek = set(entry.keys())
        if ek != REQUIRED_COHORT_FIELDS:
            return GradeResult(
                False,
                0.0,
                f"per_cohort[{i}] keys {sorted(ek)} != {sorted(REQUIRED_COHORT_FIELDS)}",
            )
        if not isinstance(entry["cohort"], str):
            return GradeResult(False, 0.0, f"per_cohort[{i}].cohort must be a string")
        if not isinstance(entry["n_pairs"], int) or isinstance(entry["n_pairs"], bool):
            return GradeResult(
                False, 0.0, f"per_cohort[{i}].n_pairs must be a non-bool integer"
            )
        for fld in ("mean_diff", "statistic", "pvalue"):
            v = entry[fld]
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                return GradeResult(
                    False, 0.0, f"per_cohort[{i}].{fld} must be a number"
                )
        if not isinstance(entry["reject_null"], bool):
            return GradeResult(
                False, 0.0, f"per_cohort[{i}].reject_null must be a boolean"
            )

    names = [e["cohort"] for e in pc]
    if names != sorted(names):
        return GradeResult(
            False, 0.0, "per_cohort must be sorted ascending by cohort name"
        )
    if len(set(names)) != len(names):
        return GradeResult(False, 0.0, "per_cohort has duplicate cohort names")

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
    if not isinstance(ov["n_pairs"], int) or isinstance(ov["n_pairs"], bool):
        return GradeResult(False, 0.0, "overall.n_pairs must be a non-bool integer")
    for fld in ("mean_diff", "statistic", "pvalue"):
        v = ov[fld]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return GradeResult(False, 0.0, f"overall.{fld} must be a number")
    if not isinstance(ov["reject_null"], bool):
        return GradeResult(False, 0.0, "overall.reject_null must be a boolean")

    expected = _compute_expected(scratch_dir)
    exp_names = [e["cohort"] for e in expected["per_cohort"]]
    if names != exp_names:
        got = set(names)
        ref = set(exp_names)
        missing_c = sorted(ref - got)
        extra_c = sorted(got - ref)
        bits: list[str] = []
        if missing_c:
            bits.append(f"missing cohort(s): {missing_c}")
        if extra_c:
            bits.append(f"unexpected cohort(s): {extra_c}")
        if not bits:
            bits.append("cohort order must be ascending lexicographic")
        return GradeResult(False, 0.0, "per_cohort cohort set mismatch: " + "; ".join(bits))

    for got_entry, exp_entry in zip(pc, expected["per_cohort"]):
        cname = exp_entry["cohort"]
        if got_entry["n_pairs"] != exp_entry["n_pairs"]:
            return GradeResult(
                False,
                0.0,
                f"per_cohort[{cname}].n_pairs mismatch: got {got_entry['n_pairs']} (incorrect)",
            )
        if abs(float(got_entry["mean_diff"]) - exp_entry["mean_diff"]) > MEAN_TOL:
            return GradeResult(
                False,
                0.0,
                f"per_cohort[{cname}].mean_diff off by more than {MEAN_TOL} "
                "(check: mean of after - before within the cohort)",
            )
        if abs(float(got_entry["statistic"]) - exp_entry["statistic"]) > STAT_TOL:
            return GradeResult(
                False,
                0.0,
                f"per_cohort[{cname}].statistic off by more than {STAT_TOL} "
                "(check: ttest_rel(after, before) — after is the FIRST argument)",
            )
        if not _pval_close(float(got_entry["pvalue"]), exp_entry["pvalue"]):
            return GradeResult(
                False,
                0.0,
                f"per_cohort[{cname}].pvalue not close to scipy.stats.ttest_rel(after, before).pvalue "
                f"(got {got_entry['pvalue']:.3e})",
            )
        if bool(got_entry["reject_null"]) != exp_entry["reject_null"]:
            return GradeResult(
                False,
                0.0,
                f"per_cohort[{cname}].reject_null mismatch: got {got_entry['reject_null']} "
                f"(rule: pvalue < {ALPHA})",
            )

    eov = expected["overall"]
    if ov["n_pairs"] != eov["n_pairs"]:
        return GradeResult(
            False, 0.0, f"overall.n_pairs mismatch: got {ov['n_pairs']} (incorrect)"
        )
    if abs(float(ov["mean_diff"]) - eov["mean_diff"]) > MEAN_TOL:
        return GradeResult(
            False, 0.0,
            f"overall.mean_diff off by more than {MEAN_TOL} (check: pooled mean of after - before)",
        )
    if abs(float(ov["statistic"]) - eov["statistic"]) > STAT_TOL:
        return GradeResult(
            False, 0.0,
            f"overall.statistic off by more than {STAT_TOL} "
            "(check: ttest_rel on the full pooled after/before arrays)",
        )
    if not _pval_close(float(ov["pvalue"]), eov["pvalue"]):
        return GradeResult(
            False, 0.0,
            f"overall.pvalue not close to scipy.stats.ttest_rel(after, before).pvalue "
            f"(got {ov['pvalue']:.3e})",
        )
    if bool(ov["reject_null"]) != eov["reject_null"]:
        return GradeResult(
            False, 0.0,
            f"overall.reject_null mismatch: got {ov['reject_null']} "
            f"(rule: pvalue < {ALPHA})",
        )

    return GradeResult(
        True,
        1.0,
        f"per-cohort ({len(pc)}) and overall paired t-test results all match",
    )
