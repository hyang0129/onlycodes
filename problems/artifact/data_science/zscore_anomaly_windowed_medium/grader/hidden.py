"""Hidden grader for ``data_science__zscore_anomaly_windowed_medium``.

Recomputes the trailing-window z-score flag set (window=20, exclude
current, ddof=1, |z|>3.0, t<20 unflaggable) from
``scratch_dir/series.csv`` and compares the agent's
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
WINDOW = 20
Z_THRESHOLD = 3.0


def _compute_expected(scratch_dir: Path) -> list[int]:
    df = pd.read_csv(scratch_dir / INPUT_CSV)
    # The on-disk row order is the intended t order (rows are written in
    # 0..N-1 t order by the generator). Sort defensively in case the
    # agent or grader environment shuffled.
    df = df.sort_values("t").reset_index(drop=True)
    t = df["t"].to_numpy()
    v = df["value"].to_numpy()
    n = len(df)
    flagged: list[int] = []
    for i in range(WINDOW, n):
        window = v[i - WINDOW : i]
        mean = float(np.mean(window))
        std = float(np.std(window, ddof=1))
        if std == 0.0:
            # All-equal window: any deviating point has z=inf and IS an
            # anomaly. Engineered data avoids this, but handle defensively.
            if v[i] != mean:
                flagged.append(int(t[i]))
            continue
        z = (float(v[i]) - mean) / std
        if abs(z) > Z_THRESHOLD:
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
    if any(x < WINDOW for x in ts):
        return GradeResult(
            False,
            0.0,
            f"flagged_ts contains t < {WINDOW} (rows with an incomplete "
            "trailing window are not flaggable)",
        )

    expected = _compute_expected(scratch_dir)

    if set(ts) != set(expected):
        got = set(ts)
        ref = set(expected)
        missing_ts = sorted(ref - got)
        extra_ts = sorted(got - ref)
        bits: list[str] = []
        if missing_ts:
            bits.append(f"{len(missing_ts)} anomalous t value(s) missing")
        if extra_ts:
            bits.append(f"{len(extra_ts)} non-anomalous t value(s) incorrectly flagged")
        return GradeResult(
            False,
            0.0,
            "flagged_ts does not match the windowed z-score rule: "
            + "; ".join(bits)
            + " (check: window is rows t-20..t-1 EXCLUDING t, "
              "std uses ddof=1, threshold is |z| > 3.0, "
              "rows t<20 are unflaggable)",
        )

    return GradeResult(
        True,
        1.0,
        f"identified {len(expected)} anomalous row(s) under |z|>3 trailing-window rule",
    )
