"""Hidden grader for ``data_engineering__normalize_order_timestamps_medium``.

Recomputes the filtered + normalized order table from ``orders.csv`` in
``scratch_dir`` and compares the agent's output row-for-row after
canonical sort by ``order_id``.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


OUTPUT_REL = "output/orders_normalized.csv"
EXPECTED_COLUMNS = ["order_id", "region", "status", "placed_at_utc"]
_ISO_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_DIGITS_RE = re.compile(r"^\d+$")
_ISO_OFFSET_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}:\d{2}:\d{2})(?P<off>[+-]\d{2}:\d{2})$"
)
_SLASH_RE = re.compile(
    r"^(?P<mo>\d{2})/(?P<d>\d{2})/(?P<y>\d{4}) (?P<time>\d{2}:\d{2}:\d{2}) (?P<tz>[A-Z]{3,4})$"
)

_TZ_TABLE = {
    "UTC": 0,
    "EST": -5 * 60,
    "EDT": -4 * 60,
    "PST": -8 * 60,
    "PDT": -7 * 60,
}


def _parse_iso_offset(value: str) -> datetime:
    m = _ISO_OFFSET_RE.match(value)
    assert m, f"unexpected ISO value {value!r}"
    sign = 1 if m["off"].startswith("+") else -1
    hh, mm = m["off"][1:].split(":")
    delta = timedelta(hours=int(hh), minutes=int(mm)) * sign
    local = datetime.strptime(m["date"] + "T" + m["time"], "%Y-%m-%dT%H:%M:%S")
    return (local - delta).replace(tzinfo=timezone.utc)


def _parse_epoch_ms(value: str) -> datetime:
    ms = int(value)
    # Truncate toward whole seconds (drop sub-second).
    return datetime.fromtimestamp(ms // 1000, tz=timezone.utc)


def _parse_slash_tz(value: str) -> datetime:
    m = _SLASH_RE.match(value)
    assert m, f"unexpected slash value {value!r}"
    tz_offset = _TZ_TABLE[m["tz"]]
    local = datetime.strptime(
        f"{m['y']}-{m['mo']}-{m['d']}T{m['time']}", "%Y-%m-%dT%H:%M:%S"
    )
    return (local - timedelta(minutes=tz_offset)).replace(tzinfo=timezone.utc)


def _parse_placed_at(raw: str) -> datetime:
    value = raw.strip()
    if _DIGITS_RE.match(value):
        return _parse_epoch_ms(value)
    if "/" in value:
        return _parse_slash_tz(value)
    return _parse_iso_offset(value)


def _format_iso_z(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compute_expected(scratch_dir: Path) -> list[dict]:
    out: list[dict] = []
    with open(scratch_dir / "orders.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["status"] == "cancelled":
                continue
            placed_raw = r["placed_at"]
            if placed_raw.strip() == "":
                continue
            ts = _parse_placed_at(placed_raw)
            out.append(
                {
                    "order_id": r["order_id"],
                    "region": r["region"],
                    "status": r["status"],
                    "placed_at_utc": _format_iso_z(ts),
                }
            )
    out.sort(key=lambda x: x["order_id"])
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
            f"row count mismatch: got {len(agent_rows)}, "
            f"{len(expected)} after dropping cancelled and empty-placed_at rows",
        )

    parsed: list[dict] = []
    for i, row in enumerate(agent_rows, start=1):
        if len(row) != len(EXPECTED_COLUMNS):
            return GradeResult(
                False, 0.0, f"row {i} has {len(row)} fields, not {len(EXPECTED_COLUMNS)}"
            )
        order_id, region, status, ts_s = row
        if status == "cancelled":
            return GradeResult(
                False, 0.0, f"row {i}: cancelled order leaked into output"
            )
        if not _ISO_Z_RE.match(ts_s):
            return GradeResult(
                False,
                0.0,
                f"row {i}: placed_at_utc {ts_s!r} must match YYYY-MM-DDTHH:MM:SSZ",
            )
        parsed.append(
            {
                "order_id": order_id,
                "region": region,
                "status": status,
                "placed_at_utc": ts_s,
            }
        )

    if [r["order_id"] for r in parsed] != [r["order_id"] for r in expected]:
        return GradeResult(
            False, 0.0, "rows not sorted by order_id ascending (or set differs)"
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
        f"normalized {len(expected)} orders after dropping cancelled/empty rows",
    )
