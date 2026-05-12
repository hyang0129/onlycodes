"""Structural verifier for ``data_engineering__dedup_event_log_priority_hard``.

Checks ``output/events_canonical.csv`` exists, has the required header in
order, and that every row has plausible types. Does NOT compare against
the reference answer.
"""

from __future__ import annotations

import csv
import re
import sys
from datetime import datetime
from pathlib import Path


EXPECTED_COLUMNS = [
    "tenant_id",
    "entity_id",
    "event_kind",
    "event_id",
    "status",
    "version",
    "received_at_utc",
]
_VALID_STATUS = {"COMMITTED", "RETRIED", "PENDING", "FAILED"}
_VALID_KIND = {"created", "updated", "deleted", "archived"}
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


def main(scratch_dir: str | None = None) -> None:
    base = Path(scratch_dir) if scratch_dir else Path(__file__).parent
    output_path = base / "output" / "events_canonical.csv"

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
        _, _, kind, _, status, version_s, ts_s = row
        if kind not in _VALID_KIND:
            errors.append(f"row {i}: event_kind {kind!r} not in {sorted(_VALID_KIND)}")
        if status not in _VALID_STATUS:
            errors.append(
                f"row {i}: status {status!r} not in {sorted(_VALID_STATUS)}"
            )
        if not version_s.isdigit():
            errors.append(
                f"row {i}: version {version_s!r} must be a plain integer (no 'v' prefix)"
            )
        if not _TS_RE.match(ts_s):
            errors.append(
                f"row {i}: received_at_utc {ts_s!r} must match "
                "YYYY-MM-DDTHH:MM:SS.ffffffZ"
            )
        else:
            try:
                datetime.strptime(ts_s, "%Y-%m-%dT%H:%M:%S.%fZ")
            except ValueError:
                errors.append(
                    f"row {i}: received_at_utc {ts_s!r} parsed shape OK but "
                    "value is not a valid datetime"
                )

    if errors:
        for err in errors[:20]:
            print(f"FAIL: {err}")
        if len(errors) > 20:
            print(f"FAIL: ... and {len(errors) - 20} more")
        sys.exit(1)

    print(f"OK: output/events_canonical.csv has {len(rows)} structurally valid rows")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
