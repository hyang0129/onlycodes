"""Hidden grader for ``data_engineering__filter_aggregate_sales_easy``.

Recomputes the per-category summary of completed orders from both source
files and compares the agent's output row-for-row.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

_CATEGORIES = ["clothing", "electronics", "food", "home", "sports"]
EXPECTED_COLUMNS = ["category", "completed_orders", "total_amount"]
OUTPUT_REL = "output/category_summary.csv"


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


def _parse_amount(raw: str) -> float:
    return float(raw.strip())


def _compute_expected(scratch_dir: Path) -> list[dict]:
    counts: dict[str, int] = {c: 0 for c in _CATEGORIES}
    totals: dict[str, float] = {c: 0.0 for c in _CATEGORIES}

    for filename in ("sales_region_a.csv", "sales_region_b.csv"):
        path = scratch_dir / filename
        with open(path, newline="") as fh:
            for row in csv.DictReader(fh):
                if row["status"] != "completed":
                    continue
                cat = row["category"]
                counts[cat] += 1
                totals[cat] += _parse_amount(row["amount"])

    result = []
    for cat in sorted(_CATEGORIES):
        result.append(
            {
                "category": cat,
                "completed_orders": counts[cat],
                "total_amount": f"{totals[cat]:.2f}",
            }
        )
    return result


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
                f"row {i}: category {cat!r} does not match expected order (expected {exp['category']!r})",
            )

        try:
            count = int(count_s)
        except ValueError:
            return GradeResult(
                False, 0.0, f"row {i}: completed_orders {count_s!r} is not an integer"
            )

        if count != exp["completed_orders"]:
            return GradeResult(
                False,
                0.0,
                f"row {i} ({cat}): completed_orders count disagrees with expected value",
            )

        try:
            total = float(total_s)
        except ValueError:
            return GradeResult(
                False, 0.0, f"row {i}: total_amount {total_s!r} is not numeric"
            )

        exp_total = float(exp["total_amount"])
        if abs(total - exp_total) > 0.005:
            return GradeResult(
                False,
                0.0,
                f"row {i} ({cat}): total_amount disagrees with expected value",
            )

        if "." not in total_s or len(total_s.split(".")[-1]) != 2:
            return GradeResult(
                False,
                0.0,
                f"row {i}: total_amount {total_s!r} must have exactly 2 decimal places",
            )

    return GradeResult(
        True,
        1.0,
        f"all {len(expected)} category rows match (filter + aggregate across both files)",
    )
