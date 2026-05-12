"""Structural verifier for ``data_engineering__filter_aggregate_support_tickets_medium``.

Checks ``output/priority_resolved_summary.csv`` exists, has the required
header, and that every row is structurally valid.  Does NOT compare against
the reference answer.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

EXPECTED_COLUMNS = ["category", "ticket_count", "total_cost"]
VALID_CATEGORIES = {"billing", "hardware", "network", "security", "software"}


def main(scratch_dir: str | None = None) -> None:
    base = Path(scratch_dir) if scratch_dir else Path(__file__).parent
    output_path = base / "output" / "priority_resolved_summary.csv"

    if not output_path.is_file():
        print(f"FAIL: output artifact not found: {output_path}")
        sys.exit(1)

    errors: list[str] = []

    with open(output_path, newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            print("FAIL: output artifact is empty")
            sys.exit(1)
        rows = list(reader)

    if header != EXPECTED_COLUMNS:
        errors.append(
            f"header must be {EXPECTED_COLUMNS} (in order); got {header}"
        )

    if not rows:
        errors.append("output has a header but zero data rows")

    for i, row in enumerate(rows, start=1):
        if len(row) != 3:
            errors.append(f"row {i}: expected 3 fields, got {len(row)}")
            continue
        cat, count_s, total_s = row
        if cat not in VALID_CATEGORIES:
            errors.append(f"row {i}: category {cat!r} not in {sorted(VALID_CATEGORIES)}")
        try:
            count = int(count_s)
            if count < 0:
                errors.append(f"row {i}: ticket_count {count_s!r} must be >= 0")
        except ValueError:
            errors.append(f"row {i}: ticket_count {count_s!r} is not an integer")
        if "." not in total_s or len(total_s.split(".")[-1]) != 2:
            errors.append(
                f"row {i}: total_cost {total_s!r} must have exactly 2 decimal places"
            )
        else:
            try:
                float(total_s)
            except ValueError:
                errors.append(f"row {i}: total_cost {total_s!r} is not numeric")

    if errors:
        for err in errors[:20]:
            print(f"FAIL: {err}")
        if len(errors) > 20:
            print(f"FAIL: ... and {len(errors) - 20} more")
        sys.exit(1)

    print(
        f"OK: output/priority_resolved_summary.csv has {len(rows)} structurally valid rows"
    )
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
