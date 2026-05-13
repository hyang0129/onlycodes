"""Hidden grader for ``data_science__rolling_mean_simple_easy``.

Recomputes the trailing 7-row rolling mean from ``scratch_dir/daily.csv``
and compares the agent's ``output/result.json`` field-by-field. All-or-
nothing scoring.
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


INPUT_CSV = "daily.csv"
OUTPUT_REL = "output/result.json"
REQUIRED_TOP = {"rolling"}
REQUIRED_ENTRY = {"t", "rolling_mean"}
WINDOW = 7
MEAN_TOL = 1e-4


def _compute_expected(scratch_dir: Path) -> list[dict]:
    df = pd.read_csv(scratch_dir / INPUT_CSV).sort_values("t").reset_index(drop=True)
    t = df["t"].to_numpy()
    v = df["value"].to_numpy()
    n = len(df)
    rows: list[dict] = []
    for i in range(WINDOW - 1, n):
        window = v[i - WINDOW + 1 : i + 1]
        rows.append({"t": int(t[i]), "rolling_mean": float(np.mean(window))})
    return rows


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

    rolling = data["rolling"]
    if not isinstance(rolling, list):
        return GradeResult(False, 0.0, "rolling must be a list")
    for i, entry in enumerate(rolling):
        if not isinstance(entry, dict):
            return GradeResult(False, 0.0, f"rolling[{i}] must be an object")
        ek = set(entry.keys())
        if ek != REQUIRED_ENTRY:
            return GradeResult(
                False, 0.0,
                f"rolling[{i}] keys {sorted(ek)} != {sorted(REQUIRED_ENTRY)}",
            )
        if not isinstance(entry["t"], int) or isinstance(entry["t"], bool):
            return GradeResult(False, 0.0, f"rolling[{i}].t must be a non-bool integer")
        v = entry["rolling_mean"]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return GradeResult(False, 0.0, f"rolling[{i}].rolling_mean must be a number")

    ts = [e["t"] for e in rolling]
    if ts != sorted(ts):
        return GradeResult(False, 0.0, "rolling entries must be sorted ascending by t")
    if len(set(ts)) != len(ts):
        return GradeResult(False, 0.0, "rolling has duplicate t values")
    if any(t < WINDOW - 1 for t in ts):
        return GradeResult(
            False, 0.0,
            f"rolling contains t < {WINDOW - 1} (incomplete-window rows must not be emitted)",
        )

    expected = _compute_expected(scratch_dir)
    exp_ts = [e["t"] for e in expected]
    if ts != exp_ts:
        got = set(ts)
        ref = set(exp_ts)
        missing_t = sorted(ref - got)
        extra_t = sorted(got - ref)
        bits: list[str] = []
        if missing_t:
            bits.append(f"{len(missing_t)} t value(s) missing")
        if extra_t:
            bits.append(f"{len(extra_t)} t value(s) extra")
        if not bits:
            bits.append("t order must be ascending")
        return GradeResult(
            False, 0.0,
            "rolling t set mismatch: " + "; ".join(bits)
            + f" (expected exactly the rows where t >= {WINDOW-1}, in t order)",
        )

    for got_e, exp_e in zip(rolling, expected):
        if abs(float(got_e["rolling_mean"]) - exp_e["rolling_mean"]) > MEAN_TOL:
            return GradeResult(
                False, 0.0,
                f"rolling[t={exp_e['t']}].rolling_mean off by more than {MEAN_TOL} "
                "(check: trailing window of 7 rows including the current row, "
                "arithmetic mean = sum/7)",
            )

    return GradeResult(
        True,
        1.0,
        f"all {len(expected)} trailing 7-row rolling means within ±{MEAN_TOL}",
    )
