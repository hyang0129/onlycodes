"""Structural verifier for ``ml_engineering__select_constrained_*``.

Spot-checks that ``output/selected.csv`` has the right header, exactly
20 rows, no duplicate run_ids, numeric val_acc, and that the rows are
sorted by val_acc descending with run_id ascending as tiebreak. Does
NOT compare against the reference — that's the hidden grader's job.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path


EXPECTED_COLUMNS = ["run_id", "val_acc"]
EXPECTED_ROWS = 20


def main(scratch_dir: str | None = None) -> None:
    base = Path(scratch_dir) if scratch_dir else Path(__file__).parent
    output_path = base / "output" / "selected.csv"

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
        errors.append(f"header must be {EXPECTED_COLUMNS}; got {header}")

    if len(rows) != EXPECTED_ROWS:
        errors.append(f"expected exactly {EXPECTED_ROWS} rows; got {len(rows)}")

    parsed: list[tuple[str, float]] = []
    seen: set[str] = set()
    for i, row in enumerate(rows, start=1):
        if len(row) != 2:
            errors.append(f"row {i}: expected 2 fields, got {len(row)}")
            continue
        rid, va_s = row[0].strip(), row[1].strip()
        if not rid:
            errors.append(f"row {i}: run_id is empty")
        if rid in seen:
            errors.append(f"row {i}: duplicate run_id {rid!r}")
        seen.add(rid)
        try:
            va = float(va_s)
            parsed.append((rid, va))
        except ValueError:
            errors.append(f"row {i}: val_acc {va_s!r} is not numeric")

    # Sort order check.
    for i in range(len(parsed) - 1):
        (rid_a, va_a), (rid_b, va_b) = parsed[i], parsed[i + 1]
        if va_a < va_b - 1e-9:
            errors.append(
                f"sort order at rows {i+1},{i+2}: val_acc must be descending; "
                f"got {va_a} then {va_b}"
            )
            break
        if abs(va_a - va_b) <= 1e-9 and rid_a > rid_b:
            errors.append(
                f"tiebreak at rows {i+1},{i+2}: val_acc tied at {va_a} but "
                f"run_ids {rid_a!r} > {rid_b!r}"
            )
            break

    if errors:
        for err in errors[:20]:
            print(f"FAIL: {err}")
        if len(errors) > 20:
            print(f"FAIL: ... and {len(errors) - 20} more")
        sys.exit(1)

    print(f"OK: output/selected.csv has {len(rows)} structurally valid rows")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
