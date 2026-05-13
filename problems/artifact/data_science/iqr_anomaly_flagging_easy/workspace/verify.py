"""Structural verifier for ``data_science__iqr_anomaly_flagging_easy``.

Checks ``output/result.json`` exists, parses as JSON, has the single required
field ``flagged_ids`` as a sorted list of unique integers. Does NOT compare
against the reference answer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


REQUIRED_FIELDS = {"flagged_ids"}


def main(scratch_dir: str | None = None) -> None:
    base = Path(scratch_dir) if scratch_dir else Path(__file__).parent
    output_path = base / "output" / "result.json"

    if not output_path.is_file():
        print(f"FAIL: output artifact not found: {output_path}")
        sys.exit(1)

    try:
        data = json.loads(output_path.read_text())
    except json.JSONDecodeError as exc:
        print(f"FAIL: output is not valid JSON: {exc}")
        sys.exit(1)

    if not isinstance(data, dict):
        print(f"FAIL: top-level JSON must be an object; got {type(data).__name__}")
        sys.exit(1)

    keys = set(data.keys())
    missing = REQUIRED_FIELDS - keys
    extra = keys - REQUIRED_FIELDS
    errors: list[str] = []
    if missing:
        errors.append(f"missing required field(s): {sorted(missing)}")
    if extra:
        errors.append(f"unexpected extra field(s): {sorted(extra)}")

    fids = data.get("flagged_ids")
    if not isinstance(fids, list) or not all(
        isinstance(x, int) and not isinstance(x, bool) for x in fids
    ):
        errors.append("flagged_ids must be a list of integers")
    else:
        if fids != sorted(fids):
            errors.append("flagged_ids must be sorted in ascending order")
        if len(set(fids)) != len(fids):
            errors.append("flagged_ids contains duplicates")

    if errors:
        for err in errors:
            print(f"FAIL: {err}")
        sys.exit(1)

    print(f"OK: result.json flags {len(data['flagged_ids'])} id(s)")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
