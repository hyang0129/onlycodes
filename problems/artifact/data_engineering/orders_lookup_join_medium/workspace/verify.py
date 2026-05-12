"""Structural verifier for ``data_engineering__orders_lookup_join_medium``.

Checks ``output/enriched_orders.csv`` exists, has the required header in
order, and that every row has plausible types. Does NOT compare against
the reference answer.
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path


EXPECTED_COLUMNS = [
    "order_id",
    "order_date",
    "customer_name",
    "customer_email",
    "product_name",
    "category",
    "quantity",
    "unit_price",
    "line_total",
]


def main(scratch_dir: str | None = None) -> None:
    base = Path(scratch_dir) if scratch_dir else Path(__file__).parent
    output_path = base / "output" / "enriched_orders.csv"

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
        _, odate, _, _, _, _, qty_s, price_s, lt_s = row
        try:
            datetime.strptime(odate, "%Y-%m-%d")
        except ValueError:
            errors.append(f"row {i}: order_date {odate!r} is not ISO YYYY-MM-DD")
        if not qty_s.isdigit():
            errors.append(f"row {i}: quantity {qty_s!r} must be a plain integer")
        for label, s in (("unit_price", price_s), ("line_total", lt_s)):
            if "." not in s or len(s.split(".")[-1]) != 2:
                errors.append(
                    f"row {i}: {label} {s!r} must have exactly 2 decimal places"
                )
                continue
            try:
                float(s)
            except ValueError:
                errors.append(f"row {i}: {label} {s!r} is not numeric")

    if errors:
        for err in errors[:20]:
            print(f"FAIL: {err}")
        if len(errors) > 20:
            print(f"FAIL: ... and {len(errors) - 20} more")
        sys.exit(1)

    print(f"OK: output/enriched_orders.csv has {len(rows)} structurally valid rows")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
