"""Structural verifier for ``data_science__train_test_split_evaluate_easy``.

Checks ``output/result.json`` exists, parses as JSON, has exactly the three
required fields with the right types. Does NOT compare against the reference
answer (that is the hidden grader's job).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


REQUIRED_FIELDS = {"rmse", "n_train", "n_test"}


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

    if "rmse" in data and not isinstance(data["rmse"], (int, float)):
        errors.append(f"rmse must be a number; got {type(data['rmse']).__name__}")
    if "n_train" in data and not (isinstance(data["n_train"], int) and not isinstance(data["n_train"], bool)):
        errors.append(f"n_train must be a non-bool integer; got {type(data['n_train']).__name__}")
    if "n_test" in data and not (isinstance(data["n_test"], int) and not isinstance(data["n_test"], bool)):
        errors.append(f"n_test must be a non-bool integer; got {type(data['n_test']).__name__}")

    if errors:
        for err in errors:
            print(f"FAIL: {err}")
        sys.exit(1)

    print(
        f"OK: result.json has rmse={data['rmse']}, "
        f"n_train={data['n_train']}, n_test={data['n_test']}"
    )
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
