"""Hidden grader for ``data_engineering__filter_aggregate_support_tickets_medium``.

Recomputes the expected per-category summary from all three source files and
compares the agent's output row-for-row.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

_CATEGORIES = ["billing", "hardware", "network", "security", "software"]
EXPECTED_COLUMNS = ["category", "ticket_count", "total_cost"]
OUTPUT_REL = "output/priority_resolved_summary.csv"
_HIGH_PRIORITY = {"high", "critical"}


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


def _parse_cost(raw: str) -> float:
    s = raw.strip()
    if s.startswith("$"):
        s = s[1:]
    return float(s)


def _is_resolved_west(row: dict) -> bool:
    return row["resolved"] == "1"


def _is_resolved_east(row: dict) -> bool:
    return row["is_resolved"] == "true"


def _is_resolved_central(row: dict) -> bool:
    return row["status"] == "closed"


def _compute_expected(scratch_dir: Path) -> list[dict]:
    counts: dict[str, int] = {c: 0 for c in _CATEGORIES}
    totals: dict[str, float] = {c: 0.0 for c in _CATEGORIES}

    # West: resolved column is "1"/"0"
    with open(scratch_dir / "tickets_west.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            if not _is_resolved_west(row):
                continue
            if row["priority"] not in _HIGH_PRIORITY:
                continue
            cat = row["category"]
            counts[cat] += 1
            totals[cat] += _parse_cost(row["cost_usd"])

    # East: is_resolved column is "true"/"false"
    with open(scratch_dir / "tickets_east.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            if not _is_resolved_east(row):
                continue
            if row["priority"] not in _HIGH_PRIORITY:
                continue
            cat = row["category"]
            counts[cat] += 1
            totals[cat] += _parse_cost(row["cost_usd"])

    # Central: dept column, status column is "closed"/"open"
    with open(scratch_dir / "tickets_central.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            if not _is_resolved_central(row):
                continue
            if row["priority"] not in _HIGH_PRIORITY:
                continue
            cat = row["dept"]
            counts[cat] += 1
            totals[cat] += _parse_cost(row["cost_usd"])

    return [
        {
            "category": cat,
            "ticket_count": counts[cat],
            "total_cost": f"{totals[cat]:.2f}",
        }
        for cat in sorted(_CATEGORIES)
    ]


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
            agent_rows = list(reader)
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
            f"row count mismatch: expected {len(expected)} rows (one per category), got {len(agent_rows)}",
        )

    for i, (row, exp) in enumerate(zip(agent_rows, expected), start=1):
        if len(row) != 3:
            return GradeResult(
                False, 0.0, f"row {i} has {len(row)} fields, expected 3"
            )
        cat, count_s, total_s = row

        if cat != exp["category"]:
            return GradeResult(
                False,
                0.0,
                f"row {i}: category {cat!r} out of expected alphabetical order (expected {exp['category']!r})",
            )

        try:
            count = int(count_s)
        except ValueError:
            return GradeResult(
                False, 0.0, f"row {i}: ticket_count {count_s!r} is not an integer"
            )

        if count != exp["ticket_count"]:
            return GradeResult(
                False,
                0.0,
                f"row {i} ({cat}): ticket_count disagrees with expected value",
            )

        try:
            total = float(total_s)
        except ValueError:
            return GradeResult(
                False, 0.0, f"row {i}: total_cost {total_s!r} is not numeric"
            )

        exp_total = float(exp["total_cost"])
        if abs(total - exp_total) > 0.005:
            return GradeResult(
                False,
                0.0,
                f"row {i} ({cat}): total_cost disagrees with expected value",
            )

        if "." not in total_s or len(total_s.split(".")[-1]) != 2:
            return GradeResult(
                False,
                0.0,
                f"row {i}: total_cost {total_s!r} must have exactly 2 decimal places",
            )

    return GradeResult(
        True,
        1.0,
        f"all {len(expected)} category rows match (filter+aggregate across 3 schema-inconsistent files)",
    )
