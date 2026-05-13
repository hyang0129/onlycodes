"""Hidden grader for ``data_science__multigroup_mannwhitney_hard``.

Recomputes pairwise Mann-Whitney U tests with Bonferroni correction
from ``scratch_dir/measurements.csv`` and compares the agent's
``output/result.json`` field-by-field. All-or-nothing scoring.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from itertools import combinations
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
U_TOL = 1e-4
PVAL_REL_TOL = 1e-3
PVAL_ABS_TOL = 1e-15
ALPHA_ABS_TOL = 1e-12
REQUIRED_TOP = {"alpha", "alpha_corrected", "n_pairs", "pairs"}
REQUIRED_PAIR_FIELDS = {
    "group_a", "group_b", "n_a", "n_b", "U", "pvalue", "reject_null",
}


def _compute_expected(scratch_dir: Path) -> dict:
    df = pd.read_csv(scratch_dir / INPUT_CSV)
    groups = sorted(str(g) for g in df["group"].unique())
    pair_names = list(combinations(groups, 2))
    n_pairs = len(pair_names)
    alpha_corrected = ALPHA / n_pairs

    pairs = []
    for ga, gb in pair_names:
        va = df.loc[df["group"] == ga, "value"].to_numpy()
        vb = df.loc[df["group"] == gb, "value"].to_numpy()
        res = stats.mannwhitneyu(
            va, vb, alternative="two-sided", use_continuity=True, method="auto"
        )
        pairs.append(
            {
                "group_a": ga,
                "group_b": gb,
                "n_a": int(len(va)),
                "n_b": int(len(vb)),
                "U": float(res.statistic),
                "pvalue": float(res.pvalue),
                "reject_null": bool(float(res.pvalue) < alpha_corrected),
            }
        )
    return {
        "alpha": ALPHA,
        "alpha_corrected": alpha_corrected,
        "n_pairs": n_pairs,
        "pairs": pairs,
    }


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

    for fld in ("alpha", "alpha_corrected"):
        v = data[fld]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return GradeResult(False, 0.0, f"{fld} must be a number")
    if not isinstance(data["n_pairs"], int) or isinstance(data["n_pairs"], bool):
        return GradeResult(False, 0.0, "n_pairs must be a non-bool integer")

    pairs = data["pairs"]
    if not isinstance(pairs, list):
        return GradeResult(False, 0.0, "pairs must be a list")
    seen_keys: list[tuple[str, str]] = []
    for i, entry in enumerate(pairs):
        if not isinstance(entry, dict):
            return GradeResult(False, 0.0, f"pairs[{i}] must be an object")
        ek = set(entry.keys())
        if ek != REQUIRED_PAIR_FIELDS:
            return GradeResult(
                False,
                0.0,
                f"pairs[{i}] keys {sorted(ek)} != {sorted(REQUIRED_PAIR_FIELDS)}",
            )
        ga, gb = entry["group_a"], entry["group_b"]
        if not (isinstance(ga, str) and isinstance(gb, str)):
            return GradeResult(False, 0.0, f"pairs[{i}].group_a/group_b must be strings")
        if not (ga < gb):
            return GradeResult(
                False, 0.0,
                f"pairs[{i}] must have group_a < group_b (got {ga!r}, {gb!r})",
            )
        seen_keys.append((ga, gb))
        for fld in ("n_a", "n_b"):
            if not isinstance(entry[fld], int) or isinstance(entry[fld], bool):
                return GradeResult(
                    False, 0.0, f"pairs[{i}].{fld} must be a non-bool integer"
                )
        for fld in ("U", "pvalue"):
            v = entry[fld]
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                return GradeResult(False, 0.0, f"pairs[{i}].{fld} must be a number")
        if not isinstance(entry["reject_null"], bool):
            return GradeResult(False, 0.0, f"pairs[{i}].reject_null must be a boolean")

    if seen_keys != sorted(seen_keys):
        return GradeResult(
            False, 0.0, "pairs must be sorted ascending by (group_a, group_b)"
        )
    if len(set(seen_keys)) != len(seen_keys):
        return GradeResult(False, 0.0, "pairs contains duplicate (group_a, group_b) entries")

    expected = _compute_expected(scratch_dir)

    if abs(float(data["alpha"]) - expected["alpha"]) > ALPHA_ABS_TOL:
        return GradeResult(
            False, 0.0, f"alpha must equal {ALPHA}, got {data['alpha']}"
        )
    if abs(float(data["alpha_corrected"]) - expected["alpha_corrected"]) > ALPHA_ABS_TOL:
        return GradeResult(
            False, 0.0,
            f"alpha_corrected must equal {expected['alpha_corrected']} "
            f"(= {ALPHA} / {expected['n_pairs']}), got {data['alpha_corrected']}",
        )
    if data["n_pairs"] != expected["n_pairs"]:
        return GradeResult(
            False, 0.0,
            f"n_pairs mismatch: got {data['n_pairs']}, expected {expected['n_pairs']} "
            f"(C(k,2) for k={int(math.sqrt(2 * expected['n_pairs'] + 0.25) + 0.5)} groups)",
        )

    exp_keys = [(e["group_a"], e["group_b"]) for e in expected["pairs"]]
    if seen_keys != exp_keys:
        got = set(seen_keys)
        ref = set(exp_keys)
        missing_p = sorted(ref - got)
        extra_p = sorted(got - ref)
        bits: list[str] = []
        if missing_p:
            bits.append(f"missing pair(s): {missing_p}")
        if extra_p:
            bits.append(f"unexpected pair(s): {extra_p}")
        if not bits:
            bits.append("pairs must be sorted ascending by (group_a, group_b)")
        return GradeResult(False, 0.0, "pair set mismatch: " + "; ".join(bits))

    for got_e, exp_e in zip(pairs, expected["pairs"]):
        key = f"({exp_e['group_a']}, {exp_e['group_b']})"
        if got_e["n_a"] != exp_e["n_a"] or got_e["n_b"] != exp_e["n_b"]:
            return GradeResult(
                False, 0.0,
                f"pairs[{key}] sample size mismatch: "
                f"got n_a={got_e['n_a']}, n_b={got_e['n_b']}; "
                f"expected n_a={exp_e['n_a']}, n_b={exp_e['n_b']}",
            )
        if abs(float(got_e["U"]) - exp_e["U"]) > U_TOL:
            return GradeResult(
                False, 0.0,
                f"pairs[{key}].U off by more than {U_TOL} from scipy's "
                "mannwhitneyu(values_a, values_b, alternative='two-sided', "
                "use_continuity=True).statistic (U for the FIRST sample)",
            )
        if not _pval_close(float(got_e["pvalue"]), exp_e["pvalue"]):
            return GradeResult(
                False, 0.0,
                f"pairs[{key}].pvalue not close to scipy's mannwhitneyu pvalue "
                f"(expected ≈ {exp_e['pvalue']:.3e}, got {got_e['pvalue']:.3e})",
            )
        if bool(got_e["reject_null"]) != exp_e["reject_null"]:
            return GradeResult(
                False, 0.0,
                f"pairs[{key}].reject_null mismatch: got {got_e['reject_null']}, "
                f"expected {exp_e['reject_null']} "
                f"(rule: pvalue < alpha_corrected = {expected['alpha_corrected']})",
            )

    n_sig = sum(1 for e in expected["pairs"] if e["reject_null"])
    return GradeResult(
        True,
        1.0,
        f"all {expected['n_pairs']} pairwise Mann-Whitney results match "
        f"(α'={expected['alpha_corrected']:.5f}; {n_sig} pair(s) reject)",
    )
