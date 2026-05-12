"""Hidden grader for ``data_engineering__normalize_login_timestamps_easy``.

Recomputes the canonical UTC ISO 8601 form of every row in
``login_events.csv`` and compares the agent's output row-for-row after
canonical sort by ``event_id``.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


OUTPUT_REL = "output/logins_normalized.csv"
EXPECTED_COLUMNS = ["event_id", "user_id", "region", "login_at_utc"]
_DIGITS_RE = re.compile(r"^\d+$")
_ISO_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _parse_login_at(value: str) -> datetime:
    """Return a UTC datetime parsed from either epoch-seconds or ISO 8601 Z."""
    if _DIGITS_RE.match(value):
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _format_iso_z(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compute_expected(scratch_dir: Path) -> list[dict]:
    out: list[dict] = []
    with open(scratch_dir / "login_events.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            ts = _parse_login_at(r["login_at"])
            out.append(
                {
                    "event_id": r["event_id"],
                    "user_id": r["user_id"],
                    "region": r["region"],
                    "login_at_utc": _format_iso_z(ts),
                }
            )
    out.sort(key=lambda x: x["event_id"])
    return out


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    output_path = scratch_dir / OUTPUT_REL

    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        with open(output_path, newline="") as fh:
            reader = csv.reader(fh)
            try:
                header = next(reader)
            except StopIteration:
                return GradeResult(False, 0.0, "output artifact is empty")
            agent_rows = [row for row in reader]
    except Exception as exc:
        return GradeResult(False, 0.0, f"could not parse output: {exc}")

    if header != EXPECTED_COLUMNS:
        return GradeResult(
            False,
            0.0,
            f"column header must be exactly {EXPECTED_COLUMNS} in that order; got {header}",
        )

    expected = _compute_expected(scratch_dir)

    if len(agent_rows) != len(expected):
        return GradeResult(
            False,
            0.0,
            f"row count mismatch: got {len(agent_rows)}, expected one row per "
            f"input login = {len(expected)}",
        )

    parsed: list[dict] = []
    for i, row in enumerate(agent_rows, start=1):
        if len(row) != len(EXPECTED_COLUMNS):
            return GradeResult(
                False, 0.0, f"row {i} has {len(row)} fields, not {len(EXPECTED_COLUMNS)}"
            )
        event_id, user_id, region, ts_s = row
        if not _ISO_Z_RE.match(ts_s):
            return GradeResult(
                False,
                0.0,
                f"row {i}: login_at_utc {ts_s!r} must match YYYY-MM-DDTHH:MM:SSZ",
            )
        parsed.append(
            {
                "event_id": event_id,
                "user_id": user_id,
                "region": region,
                "login_at_utc": ts_s,
            }
        )

    if [r["event_id"] for r in parsed] != [r["event_id"] for r in expected]:
        return GradeResult(
            False, 0.0, "rows not sorted by event_id ascending (or set differs)"
        )

    for i, (a, e) in enumerate(zip(parsed, expected), start=1):
        for k in EXPECTED_COLUMNS:
            if a[k] != e[k]:
                return GradeResult(
                    False,
                    0.0,
                    f"row {i}: {k} value disagrees with the expected normalization",
                )

    return GradeResult(
        True,
        1.0,
        f"normalized {len(expected)} login timestamps to canonical UTC ISO 8601",
    )
