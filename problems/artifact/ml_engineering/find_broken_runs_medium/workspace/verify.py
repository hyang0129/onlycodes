"""Structural verifier for ``ml_engineering__find_broken_runs_*``.

Checks ``output/broken.csv`` exists, has the required header in the
required column order, every row has exactly two fields, and every
``failure_mode`` value is one of ``nan``, ``truncated``, ``diverged``.

Does NOT compare against the reference answer — that is the hidden
grader's job. Use this to spot-check formatting before believing a run
was successful.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path


EXPECTED_COLUMNS = ["run_id", "failure_mode"]
VALID_MODES = {"nan", "truncated", "diverged"}


def main(scratch_dir: str | None = None) -> None:
    base = Path(scratch_dir) if scratch_dir else Path(__file__).parent
    output_path = base / "output" / "broken.csv"

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

    seen: set[str] = set()
    for i, row in enumerate(rows, start=1):
        if len(row) != 2:
            errors.append(f"row {i}: expected 2 fields, got {len(row)}")
            continue
        run_id, mode = row[0].strip(), row[1].strip()
        if not run_id:
            errors.append(f"row {i}: run_id is empty")
        if mode not in VALID_MODES:
            errors.append(
                f"row {i}: failure_mode {mode!r} not in {sorted(VALID_MODES)}"
            )
        if run_id in seen:
            errors.append(f"row {i}: duplicate run_id {run_id!r}")
        seen.add(run_id)

    if errors:
        for err in errors[:20]:
            print(f"FAIL: {err}")
        if len(errors) > 20:
            print(f"FAIL: ... and {len(errors) - 20} more")
        sys.exit(1)

    print(f"OK: output/broken.csv has {len(rows)} structurally valid rows")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
