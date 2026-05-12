"""Structural verifier for ``data_engineering__normalize_order_timestamps_medium``.

Checks ``output/orders_normalized.csv`` exists, has the required header in
order, and that every row has plausible types. Does NOT compare against
the reference answer.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path


EXPECTED_COLUMNS = ["order_id", "region", "status", "placed_at_utc"]
_ISO_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ALLOWED_REGIONS = {"na", "eu", "apac"}
_ALLOWED_STATUSES = {"placed", "fulfilled"}


def main(scratch_dir: str | None = None) -> None:
    base = Path(scratch_dir) if scratch_dir else Path(__file__).parent
    output_path = base / "output" / "orders_normalized.csv"

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
        _, region, status, ts_s = row
        if region not in _ALLOWED_REGIONS:
            errors.append(f"row {i}: region {region!r} not in {_ALLOWED_REGIONS}")
        if status not in _ALLOWED_STATUSES:
            errors.append(
                f"row {i}: status {status!r} should have been filtered out or is unknown"
            )
        if not _ISO_Z_RE.match(ts_s):
            errors.append(
                f"row {i}: placed_at_utc {ts_s!r} must match YYYY-MM-DDTHH:MM:SSZ"
            )

    if errors:
        for err in errors[:20]:
            print(f"FAIL: {err}")
        if len(errors) > 20:
            print(f"FAIL: ... and {len(errors) - 20} more")
        sys.exit(1)

    print(f"OK: output/orders_normalized.csv has {len(rows)} structurally valid rows")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
