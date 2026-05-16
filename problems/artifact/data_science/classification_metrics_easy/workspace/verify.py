"""Structural verifier for ``data_science__classification_metrics_easy``.

Checks ``output/result.json`` exists, parses as JSON, and has exactly the
four required float fields. Does NOT compare against the reference answer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


REQUIRED_FIELDS = {"accuracy", "precision", "recall", "f1"}


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

    for field in REQUIRED_FIELDS:
        if field in data:
            v = data[field]
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                errors.append(f"{field} must be a number; got {type(v).__name__}")

    if errors:
        for err in errors:
            print(f"FAIL: {err}")
        sys.exit(1)

    print(
        f"OK: result.json has accuracy={data['accuracy']}, "
        f"precision={data['precision']}, recall={data['recall']}, f1={data['f1']}"
    )
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
