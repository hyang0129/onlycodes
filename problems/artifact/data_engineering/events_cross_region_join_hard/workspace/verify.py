"""Structural verifier for ``data_engineering__events_cross_region_join_hard``."""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path


EXPECTED_COLUMNS = [
    "event_utc_ts",
    "user_id",
    "user_tier",
    "event_type",
    "source_region",
]
VALID_EVENT_TYPES = {"page_view", "add_to_cart", "checkout", "login", "logout"}
VALID_REGIONS = {"us", "eu", "apac"}
VALID_TIERS = {"free", "pro", "enterprise"}
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def main(scratch_dir: str | None = None) -> None:
    base = Path(scratch_dir) if scratch_dir else Path(__file__).parent
    output_path = base / "output" / "events.csv"

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
        ts, uid, tier, evt, region = row
        if not _ISO_RE.match(ts):
            errors.append(f"row {i}: event_utc_ts {ts!r} must be YYYY-MM-DDTHH:MM:SSZ")
        if not uid.isdigit():
            errors.append(f"row {i}: user_id {uid!r} must be a plain integer")
        if tier not in VALID_TIERS:
            errors.append(f"row {i}: user_tier {tier!r} must be one of {sorted(VALID_TIERS)}")
        if evt not in VALID_EVENT_TYPES:
            errors.append(f"row {i}: event_type {evt!r} must be one of {sorted(VALID_EVENT_TYPES)}")
        if region not in VALID_REGIONS:
            errors.append(
                f"row {i}: source_region {region!r} must be one of {sorted(VALID_REGIONS)}"
            )

    if errors:
        for err in errors[:20]:
            print(f"FAIL: {err}")
        if len(errors) > 20:
            print(f"FAIL: ... and {len(errors) - 20} more")
        sys.exit(1)

    print(f"OK: output/events.csv has {len(rows)} structurally valid rows")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
