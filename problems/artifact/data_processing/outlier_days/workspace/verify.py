"""Public STRUCTURAL verifier for outlier_days. Shape only."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

_REQUIRED = {"region", "product", "date", "units_sold",
             "window_median", "mad", "modified_z", "direction"}


def verify(artifact_path: Path) -> None:
    artifact_path = Path(artifact_path)
    assert artifact_path.is_file(), f"artifact not found: {artifact_path}"

    raw = artifact_path.read_text()
    # Empty is shape-valid (grader will still fail if outliers exist).
    if not raw.strip():
        return

    seen: set[tuple[str, str, str]] = set()
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"line {lineno}: not valid JSON ({exc.msg})"
            ) from None
        assert isinstance(row, dict), f"line {lineno}: not object"

        keys = set(row.keys())
        missing = _REQUIRED - keys
        extra = keys - _REQUIRED
        assert not missing, f"line {lineno}: missing {sorted(missing)}"
        assert not extra, f"line {lineno}: extra {sorted(extra)}"

        region = row["region"]
        product = row["product"]
        date = row["date"]
        for name, val in (("region", region), ("product", product), ("date", date)):
            assert isinstance(val, str) and val, f"line {lineno}: {name} must be non-empty string"
        try:
            dt.date.fromisoformat(date)
        except ValueError:
            raise AssertionError(f"line {lineno}: date {date!r} not ISO") from None

        us = row["units_sold"]
        assert isinstance(us, int) and not isinstance(us, bool), (
            f"line {lineno}: units_sold must be int"
        )
        assert us >= 0, f"line {lineno}: units_sold must be >= 0"

        for name in ("window_median", "mad", "modified_z"):
            val = row[name]
            assert isinstance(val, (int, float)) and not isinstance(val, bool), (
                f"line {lineno}: {name} must be number"
            )
        assert row["mad"] >= 0, f"line {lineno}: mad must be >= 0"

        direction = row["direction"]
        assert direction in ("high", "low"), (
            f"line {lineno}: direction must be 'high' or 'low'"
        )
        z = float(row["modified_z"])
        if direction == "high":
            assert z > 0, f"line {lineno}: direction high but modified_z {z} <= 0"
        else:
            assert z < 0, f"line {lineno}: direction low but modified_z {z} >= 0"

        key = (region, product, date)
        assert key not in seen, f"line {lineno}: duplicate {key}"
        seen.add(key)
