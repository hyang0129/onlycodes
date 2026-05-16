"""Hidden grader for ``data_science__consecutive_change_anomaly_hard``.

Recomputes the "row closes a 3-period |pct_change| > 0.02 run" flag set
from ``scratch_dir/series.csv`` and compares the agent's
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


INPUT_CSV = "series.csv"
OUTPUT_REL = "output/result.json"
REQUIRED_FIELDS = {"flagged_ts"}
PCT_THRESHOLD = 0.02
RUN_LEN = 3
MIN_FLAGGABLE_T = 3


def _compute_expected(scratch_dir: Path) -> list[int]:
    df = pd.read_csv(scratch_dir / INPUT_CSV)
    df = df.sort_values("t").reset_index(drop=True)
    t = df["t"].to_numpy()
    v = df["value"].to_numpy()
    n = len(df)
    # pct_change[i] = (v[i] - v[i-1]) / v[i-1] for i >= 1; undefined at i=0.
    is_large = np.zeros(n, dtype=bool)
    for i in range(1, n):
        pc = (v[i] - v[i - 1]) / v[i - 1]
        if abs(pc) > PCT_THRESHOLD:
            is_large[i] = True
    # Row t (using i as t since rows are in t order) closes a 3-period
    # run iff is_large[t-2], is_large[t-1], is_large[t] are all True.
    flagged: list[int] = []
    for i in range(MIN_FLAGGABLE_T, n):
        if is_large[i] and is_large[i - 1] and is_large[i - 2]:
            flagged.append(int(t[i]))
    return sorted(flagged)


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

    ts = data["flagged_ts"]
    if not isinstance(ts, list) or not all(
        isinstance(x, int) and not isinstance(x, bool) for x in ts
    ):
        return GradeResult(False, 0.0, "flagged_ts must be a list of integers")
    if ts != sorted(ts):
        return GradeResult(False, 0.0, "flagged_ts must be sorted in ascending order")
    if len(set(ts)) != len(ts):
        return GradeResult(False, 0.0, "flagged_ts contains duplicates")
    if any(x < MIN_FLAGGABLE_T for x in ts):
        return GradeResult(
            False,
            0.0,
            f"flagged_ts contains t < {MIN_FLAGGABLE_T} (need 3 prior periods "
            "of pct_change to close a 3-period run)",
        )

    expected = _compute_expected(scratch_dir)

    if set(ts) != set(expected):
        got = set(ts)
        ref = set(expected)
        missing_ts = sorted(ref - got)
        extra_ts = sorted(got - ref)
        bits: list[str] = []
        if missing_ts:
            bits.append(f"{len(missing_ts)} run-closing t value(s) missing")
        if extra_ts:
            bits.append(
                f"{len(extra_ts)} non-run-closing t value(s) incorrectly flagged"
            )
        return GradeResult(
            False,
            0.0,
            "flagged_ts does not match the 3-period |pct_change|>0.02 run rule: "
            + "; ".join(bits)
            + " (check: pct_change[t]=(v[t]-v[t-1])/v[t-1] for t>=1, "
              "row t flagged iff |pct_change| at t-2, t-1, t are all > 0.02, "
              "rows t<3 unflaggable, pct_change[0] is undefined NOT zero)",
        )

    return GradeResult(
        True,
        1.0,
        f"identified {len(expected)} t value(s) closing a 3-period |pct_change|>0.02 run",
    )
