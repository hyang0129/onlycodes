"""Structural verifier for ml_engineering__aggregate_predictions_{easy,medium,hard}.

Checks that ``output/predictions.csv`` exists, is valid CSV, has the correct
header, contains only numeric pred_prob values, has no duplicate IDs, and is
sorted by ID ascending.

Does NOT check correctness against the hidden reference.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

_ID_RE = re.compile(r"^sample_\d{5}$")


def main(scratch_dir: str | None = None) -> None:
    base = Path(scratch_dir) if scratch_dir else Path(__file__).parent
    output_path = base / "output" / "predictions.csv"

    if not output_path.is_file():
        print("FAIL: output/predictions.csv not found")
        sys.exit(1)

    try:
        with open(output_path, newline="") as fh:
            reader = csv.reader(fh)
            try:
                header = next(reader)
            except StopIteration:
                print("FAIL: output/predictions.csv is empty")
                sys.exit(1)
            rows = list(reader)
    except Exception as exc:
        print(f"FAIL: could not parse output/predictions.csv: {exc}")
        sys.exit(1)

    errors: list[str] = []

    if header != ["id", "pred_prob"]:
        errors.append(f"header must be exactly ['id', 'pred_prob']; got {header}")

    seen_ids: set[str] = set()
    prev_id: str | None = None

    for i, row in enumerate(rows, start=1):
        if len(row) != 2:
            errors.append(f"row {i}: expected 2 fields, got {len(row)}")
            continue
        sid, prob_str = row[0].strip(), row[1].strip()

        if not _ID_RE.match(sid):
            errors.append(f"row {i}: id {sid!r} does not match pattern sample_NNNNN")

        if sid in seen_ids:
            errors.append(f"row {i}: duplicate id {sid!r}")
        seen_ids.add(sid)

        try:
            float(prob_str)
        except ValueError:
            errors.append(f"row {i}: pred_prob {prob_str!r} is not numeric")

        if prev_id is not None and sid < prev_id:
            errors.append(f"row {i}: id {sid!r} < previous id {prev_id!r} (must be sorted ascending)")
        prev_id = sid

        if len(errors) >= 10:
            errors.append("... (further errors suppressed)")
            break

    if errors:
        for err in errors:
            print(f"FAIL: {err}")
        sys.exit(1)

    print(f"OK: output/predictions.csv is structurally valid ({len(rows)} rows)")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
