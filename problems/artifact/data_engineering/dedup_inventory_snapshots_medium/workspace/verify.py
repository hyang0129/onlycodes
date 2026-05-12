"""Structural verifier for ``data_engineering__dedup_inventory_snapshots_medium``.

Checks ``output/inventory_current.csv`` exists, has the required header in
order, and that every row has plausible types. Does NOT compare against the
reference answer.
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path


EXPECTED_COLUMNS = [
    "warehouse_id",
    "sku",
    "on_hand_units",
    "captured_at",
    "revision",
]


def main(scratch_dir: str | None = None) -> None:
    base = Path(scratch_dir) if scratch_dir else Path(__file__).parent
    output_path = base / "output" / "inventory_current.csv"

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
        errors.append(f"header must be {EXPECTED_COLUMNS} (in order); got {header}")

    if not rows:
        errors.append("output has a header but zero data rows")

    for i, row in enumerate(rows, start=1):
        if len(row) != len(EXPECTED_COLUMNS):
            errors.append(
                f"row {i}: expected {len(EXPECTED_COLUMNS)} fields, got {len(row)}"
            )
            continue
        wh, _sku, units_s, ts_s, rev_s = row
        if wh != wh.upper():
            errors.append(f"row {i}: warehouse_id {wh!r} must be uppercased")
        if not units_s.isdigit():
            errors.append(
                f"row {i}: on_hand_units {units_s!r} must be a non-negative integer"
            )
        if not rev_s.isdigit():
            errors.append(
                f"row {i}: revision {rev_s!r} must be a non-negative integer"
            )
        try:
            datetime.strptime(ts_s, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            errors.append(
                f"row {i}: captured_at {ts_s!r} must match YYYY-MM-DDTHH:MM:SSZ "
                "(no whitespace padding in the output)"
            )

    if errors:
        for err in errors[:20]:
            print(f"FAIL: {err}")
        if len(errors) > 20:
            print(f"FAIL: ... and {len(errors) - 20} more")
        sys.exit(1)

    print(f"OK: output/inventory_current.csv has {len(rows)} structurally valid rows")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
