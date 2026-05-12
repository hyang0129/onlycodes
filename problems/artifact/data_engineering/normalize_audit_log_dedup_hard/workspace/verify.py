"""Structural verifier for ``data_engineering__normalize_audit_log_dedup_hard``.

Checks ``output/audit_canonical.csv`` exists, has the required header in
order, and that every row has plausible types. Does NOT compare against
the reference answer.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path


EXPECTED_COLUMNS = [
    "entity_id",
    "action",
    "record_id",
    "source_shard",
    "recorded_at_utc",
]
_ISO_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ALLOWED_ACTIONS = {"create", "update", "delete", "archive"}
_ALLOWED_SHARDS = {"alpha", "beta", "gamma"}


def main(scratch_dir: str | None = None) -> None:
    base = Path(scratch_dir) if scratch_dir else Path(__file__).parent
    output_path = base / "output" / "audit_canonical.csv"

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

    seen_keys: set[tuple[str, str]] = set()
    for i, row in enumerate(rows, start=1):
        if len(row) != len(EXPECTED_COLUMNS):
            errors.append(
                f"row {i}: expected {len(EXPECTED_COLUMNS)} fields, got {len(row)}"
            )
            continue
        entity_id, action, _record_id, shard, ts_s = row
        if action not in _ALLOWED_ACTIONS:
            errors.append(f"row {i}: action {action!r} not in {_ALLOWED_ACTIONS}")
        if shard not in _ALLOWED_SHARDS:
            errors.append(f"row {i}: source_shard {shard!r} not in {_ALLOWED_SHARDS}")
        if not _ISO_Z_RE.match(ts_s):
            errors.append(
                f"row {i}: recorded_at_utc {ts_s!r} must match YYYY-MM-DDTHH:MM:SSZ"
            )
        key = (entity_id, action)
        if key in seen_keys:
            errors.append(
                f"row {i}: composite key (entity_id, action)={key} appears more than once"
            )
        seen_keys.add(key)

    if errors:
        for err in errors[:20]:
            print(f"FAIL: {err}")
        if len(errors) > 20:
            print(f"FAIL: ... and {len(errors) - 20} more")
        sys.exit(1)

    print(f"OK: output/audit_canonical.csv has {len(rows)} structurally valid rows")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
