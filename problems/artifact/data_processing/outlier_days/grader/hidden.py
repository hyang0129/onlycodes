"""Hidden grader for data_processing__outlier_days.

Recomputes outliers per (region, product) series using a trailing 14-day
median+MAD modified z-score (threshold 3.5). Checks the agent's output
contains exactly the outlier days with matching fields.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


INPUT_REL = "sales.csv"
OUTPUT_REL = "output/outliers.jsonl"

WINDOW = 14
THRESHOLD = 3.5
FLOAT_TOL = 1e-3

REQUIRED = frozenset({"region", "product", "date", "units_sold",
                      "window_median", "mad", "modified_z", "direction"})


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n % 2 == 1:
        return float(s[n // 2])
    return 0.5 * (s[n // 2 - 1] + s[n // 2])


def _truth(scratch_dir: Path) -> dict[tuple[str, str, str], dict]:
    # Read all rows, group by (region, product), sort by date.
    series: dict[tuple[str, str], list[tuple[dt.date, int]]] = {}
    with open(scratch_dir / INPUT_REL, newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            key = (row["region"], row["product"])
            d = dt.date.fromisoformat(row["date"])
            us = int(row["units_sold"])
            series.setdefault(key, []).append((d, us))

    out: dict[tuple[str, str, str], dict] = {}
    for (region, product), pts in series.items():
        pts.sort(key=lambda p: p[0])
        values = [float(p[1]) for p in pts]
        dates = [p[0] for p in pts]
        for i in range(WINDOW, len(pts)):
            window = values[i - WINDOW:i]
            m = _median(window)
            mad = _median([abs(v - m) for v in window])
            x = values[i]
            if mad > 0:
                z = 0.6745 * (x - m) / mad
            else:
                if x == m:
                    z = 0.0
                elif x > m:
                    z = 9999.0
                else:
                    z = -9999.0
            if abs(z) >= THRESHOLD:
                direction = "high" if z > 0 else "low"
                out[(region, product, dates[i].isoformat())] = {
                    "region": region,
                    "product": product,
                    "date": dates[i].isoformat(),
                    "units_sold": int(pts[i][1]),
                    "window_median": round(m, 3),
                    "mad": round(mad, 3),
                    "modified_z": round(z, 3),
                    "direction": direction,
                }
    return out


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    if not (scratch_dir / INPUT_REL).is_file():
        return GradeResult(False, 0.0, f"{INPUT_REL} not found")
    outp = scratch_dir / OUTPUT_REL
    if not outp.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    truth = _truth(scratch_dir)

    seen: dict[tuple[str, str, str], dict] = {}
    for lineno, line in enumerate(outp.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            return GradeResult(False, 0.0, f"line {lineno}: bad JSON ({exc.msg})")
        if not isinstance(row, dict):
            return GradeResult(False, 0.0, f"line {lineno}: not object")
        keys = set(row.keys())
        if keys != REQUIRED:
            missing = REQUIRED - keys
            extra = keys - REQUIRED
            bits = []
            if missing:
                bits.append(f"missing {sorted(missing)}")
            if extra:
                bits.append(f"extra {sorted(extra)}")
            return GradeResult(False, 0.0, f"line {lineno}: {'; '.join(bits)}")

        key = (row["region"], row["product"], row["date"])
        if key in seen:
            return GradeResult(False, 0.0, f"line {lineno}: duplicate {key}")
        seen[key] = row

    truth_keys = set(truth.keys())
    got_keys = set(seen.keys())
    missing = sorted(truth_keys - got_keys)
    extra = sorted(got_keys - truth_keys)
    if missing:
        return GradeResult(
            False, 0.0,
            f"missing {len(missing)} outlier day(s): {missing[:3]}"
            + (" ..." if len(missing) > 3 else ""),
        )
    if extra:
        return GradeResult(
            False, 0.0,
            f"{len(extra)} non-outlier day(s) reported: {extra[:3]}"
            + (" ..." if len(extra) > 3 else ""),
        )

    for key, want in truth.items():
        got = seen[key]
        if got["units_sold"] != want["units_sold"]:
            return GradeResult(
                False, 0.0,
                f"{key}: units_sold {got['units_sold']} != expected {want['units_sold']}",
            )
        if got["direction"] != want["direction"]:
            return GradeResult(
                False, 0.0,
                f"{key}: direction {got['direction']!r} != expected {want['direction']!r}",
            )
        for field in ("window_median", "mad", "modified_z"):
            gv = got[field]
            if isinstance(gv, bool) or not isinstance(gv, (int, float)):
                return GradeResult(False, 0.0, f"{key}: {field} not number")
            if not math.isfinite(float(gv)):
                # Allow saturation sentinel values exactly.
                if field == "modified_z" and gv in (9999.0, -9999.0):
                    pass
                else:
                    return GradeResult(False, 0.0, f"{key}: {field} not finite")
            if abs(float(gv) - want[field]) > FLOAT_TOL:
                return GradeResult(
                    False, 0.0,
                    f"{key}: {field} {gv} != expected ~{want[field]}",
                )

    return GradeResult(True, 1.0, f"matched {len(truth)} outlier day(s)")
