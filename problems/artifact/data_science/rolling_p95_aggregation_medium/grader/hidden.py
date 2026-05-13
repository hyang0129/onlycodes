"""Hidden grader for ``data_science__rolling_p95_aggregation_medium``.

Recomputes the trailing-24-row rolling P95 (linear interpolation) plus
the > 200.0 flag set from ``scratch_dir/latency.csv`` and compares the
agent's ``output/result.json`` field-by-field. All-or-nothing scoring.
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


INPUT_CSV = "latency.csv"
OUTPUT_REL = "output/result.json"
REQUIRED_TOP = {"rolling", "flagged_ts"}
REQUIRED_ENTRY = {"t", "rolling_p95"}
WINDOW = 24
PERCENTILE = 0.95
THRESHOLD = 200.0
P95_TOL = 0.01  # relaxed percentile tolerance per category convention


def _compute_expected(scratch_dir: Path) -> dict:
    df = pd.read_csv(scratch_dir / INPUT_CSV).sort_values("t").reset_index(drop=True)
    t = df["t"].to_numpy()
    v = df["latency_ms"].to_numpy()
    n = len(df)
    rolling: list[dict] = []
    flagged: list[int] = []
    for i in range(WINDOW - 1, n):
        window = v[i - WINDOW + 1 : i + 1]
        p95 = float(np.quantile(window, PERCENTILE))
        rolling.append({"t": int(t[i]), "rolling_p95": p95})
        if p95 > THRESHOLD:
            flagged.append(int(t[i]))
    return {"rolling": rolling, "flagged_ts": sorted(flagged)}


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
        v = entry["rolling_p95"]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return GradeResult(False, 0.0, f"rolling[{i}].rolling_p95 must be a number")

    rolling_ts = [e["t"] for e in rolling]
    if rolling_ts != sorted(rolling_ts):
        return GradeResult(False, 0.0, "rolling entries must be sorted ascending by t")
    if len(set(rolling_ts)) != len(rolling_ts):
        return GradeResult(False, 0.0, "rolling has duplicate t values")
    if any(t < WINDOW - 1 for t in rolling_ts):
        return GradeResult(
            False, 0.0,
            f"rolling contains t < {WINDOW - 1} (incomplete-window rows must not be emitted)",
        )

    flagged = data["flagged_ts"]
    if not isinstance(flagged, list) or not all(
        isinstance(x, int) and not isinstance(x, bool) for x in flagged
    ):
        return GradeResult(False, 0.0, "flagged_ts must be a list of integers")
    if flagged != sorted(flagged):
        return GradeResult(False, 0.0, "flagged_ts must be sorted ascending")
    if len(set(flagged)) != len(flagged):
        return GradeResult(False, 0.0, "flagged_ts has duplicates")

    expected = _compute_expected(scratch_dir)
    exp_ts = [e["t"] for e in expected["rolling"]]
    if rolling_ts != exp_ts:
        got = set(rolling_ts)
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

    for got_e, exp_e in zip(rolling, expected["rolling"]):
        if abs(float(got_e["rolling_p95"]) - exp_e["rolling_p95"]) > P95_TOL:
            return GradeResult(
                False, 0.0,
                f"rolling[t={exp_e['t']}].rolling_p95 off by more than {P95_TOL} "
                "(check: trailing 24-row window including the current row; "
                "p95 via numpy.quantile linear interpolation)",
            )

    if set(flagged) != set(expected["flagged_ts"]):
        got = set(flagged)
        ref = set(expected["flagged_ts"])
        missing_f = sorted(ref - got)
        extra_f = sorted(got - ref)
        bits: list[str] = []
        if missing_f:
            bits.append(f"{len(missing_f)} threshold-exceeding t value(s) missing")
        if extra_f:
            bits.append(f"{len(extra_f)} non-exceeding t value(s) incorrectly flagged")
        return GradeResult(
            False, 0.0,
            "flagged_ts does not match the rolling_p95 > 200.0 rule: "
            + "; ".join(bits),
        )

    return GradeResult(
        True,
        1.0,
        f"rolling p95 over {len(expected['rolling'])} rows within ±{P95_TOL}; "
        f"{len(expected['flagged_ts'])} t-value(s) above {THRESHOLD}ms",
    )
