"""Structural verifier for ``data_engineering__customer_orders_join_easy``.

Checks ``output/orders_unified.csv`` exists, has the required header in the
required order, and that every row has the right number of fields with
plausible types. Does NOT compare against the reference answer.
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path


EXPECTED_COLUMNS = ["customer_id", "order_id", "order_date", "amount_usd", "source"]


def main(scratch_dir: str | None = None) -> None:
    base = Path(scratch_dir) if scratch_dir else Path(__file__).parent
    output_path = base / "output" / "orders_unified.csv"

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
        if len(row) != len(EXPECTED_COLUMNS):
            errors.append(
                f"row {i}: expected {len(EXPECTED_COLUMNS)} fields, got {len(row)}"
            )
            continue
        _, _, odate, amt, src = row
        try:
            datetime.strptime(odate, "%Y-%m-%d")
        except ValueError:
            errors.append(f"row {i}: order_date {odate!r} is not ISO YYYY-MM-DD")
        if "." not in amt or len(amt.split(".")[-1]) != 2:
            errors.append(
                f"row {i}: amount_usd {amt!r} must have exactly 2 decimal places"
            )
        else:
            try:
                float(amt)
            except ValueError:
                errors.append(f"row {i}: amount_usd {amt!r} is not numeric")
        if src not in ("north", "south"):
            errors.append(f"row {i}: source {src!r} must be 'north' or 'south'")

    if errors:
        for err in errors[:20]:
            print(f"FAIL: {err}")
        if len(errors) > 20:
            print(f"FAIL: ... and {len(errors) - 20} more")
        sys.exit(1)

    print(f"OK: output/orders_unified.csv has {len(rows)} structurally valid rows")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
