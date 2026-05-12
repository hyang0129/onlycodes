"""Structural verifier for ``data_engineering__repair_transactions_export_hard``.

Checks ``output/transactions_clean.csv`` exists, has the required header,
and that every row is structurally valid (column count, type discipline,
allowed values).  Does NOT compare against the reference output.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

EXPECTED_COLUMNS = [
    "tx_id", "account_id", "amount", "tx_type", "status",
    "is_disputed", "is_refunded", "channel", "notes",
]
VALID_TYPES = {"deposit", "withdrawal", "transfer", "fee"}
VALID_STATUSES = {"completed", "pending", "failed"}
VALID_CHANNELS = {"web", "mobile", "branch", "api"}
VALID_BOOLS = {"true", "false"}


def main(scratch_dir: str | None = None) -> None:
    base = Path(scratch_dir) if scratch_dir else Path(__file__).parent
    output_path = base / "output" / "transactions_clean.csv"

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

    seen_ids: set[str] = set()
    for i, row in enumerate(rows, start=1):
        if len(row) != 9:
            errors.append(f"row {i}: expected 9 fields, got {len(row)}")
            continue
        (tx_id, account_id, amount, tx_type, status, is_disp,
         is_ref, channel, _notes) = row

        if not tx_id.startswith("T-") or len(tx_id) != 8:
            errors.append(f"row {i}: tx_id {tx_id!r} has unexpected shape")
        if tx_id in seen_ids:
            errors.append(f"row {i}: duplicate tx_id {tx_id!r}")
        seen_ids.add(tx_id)

        if not account_id.startswith("ACCT-"):
            errors.append(f"row {i}: account_id {account_id!r} has unexpected shape")

        # amount: signed float with exactly 2 decimal places, no commas,
        # no $, no parentheses.
        if any(ch in amount for ch in ("$", ",", "(", ")")) or "USD" in amount:
            errors.append(f"row {i}: amount {amount!r} contains forbidden characters")
        elif "." not in amount or len(amount.split(".")[-1]) != 2:
            errors.append(f"row {i}: amount {amount!r} not formatted with 2 decimals")
        else:
            try:
                float(amount)
            except ValueError:
                errors.append(f"row {i}: amount {amount!r} is not numeric")

        if tx_type not in VALID_TYPES:
            errors.append(
                f"row {i}: tx_type {tx_type!r} must be one of {sorted(VALID_TYPES)}"
            )
        if status not in VALID_STATUSES:
            errors.append(
                f"row {i}: status {status!r} must be one of {sorted(VALID_STATUSES)}"
            )
        if is_disp not in VALID_BOOLS:
            errors.append(f"row {i}: is_disputed {is_disp!r} must be true/false")
        if is_ref not in VALID_BOOLS:
            errors.append(f"row {i}: is_refunded {is_ref!r} must be true/false")
        if channel not in VALID_CHANNELS:
            errors.append(
                f"row {i}: channel {channel!r} must be one of {sorted(VALID_CHANNELS)}"
            )

    ids = [r[0] for r in rows if len(r) == 9]
    if ids != sorted(ids):
        errors.append("rows are not sorted by tx_id ascending")

    if errors:
        for err in errors[:20]:
            print(f"FAIL: {err}")
        if len(errors) > 20:
            print(f"FAIL: ... and {len(errors) - 20} more")
        sys.exit(1)

    print(f"OK: output/transactions_clean.csv has {len(rows)} structurally valid rows")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
