"""Structural verifier for ``data_engineering__transactions_union_medium``."""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path


EXPECTED_COLUMNS = ["tx_id", "tx_date", "amount_native", "currency_code"]
VALID_CURRENCIES = {"USD", "EUR", "GBP"}


def main(scratch_dir: str | None = None) -> None:
    base = Path(scratch_dir) if scratch_dir else Path(__file__).parent
    output_path = base / "output" / "transactions.csv"

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
        _, tx_date, amt, cc = row
        try:
            datetime.strptime(tx_date, "%Y-%m-%d")
        except ValueError:
            errors.append(f"row {i}: tx_date {tx_date!r} is not ISO YYYY-MM-DD")
        if "." not in amt or len(amt.split(".")[-1]) != 2:
            errors.append(
                f"row {i}: amount_native {amt!r} must have exactly 2 decimal places"
            )
        else:
            try:
                float(amt)
            except ValueError:
                errors.append(f"row {i}: amount_native {amt!r} is not numeric")
        if cc not in VALID_CURRENCIES:
            errors.append(
                f"row {i}: currency_code {cc!r} must be one of {sorted(VALID_CURRENCIES)}"
            )

    if errors:
        for err in errors[:20]:
            print(f"FAIL: {err}")
        if len(errors) > 20:
            print(f"FAIL: ... and {len(errors) - 20} more")
        sys.exit(1)

    print(f"OK: output/transactions.csv has {len(rows)} structurally valid rows")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
