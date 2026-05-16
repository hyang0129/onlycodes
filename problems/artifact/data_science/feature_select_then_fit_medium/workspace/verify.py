"""Structural verifier for ``data_science__feature_select_then_fit_medium``.

Checks ``output/result.json`` exists, parses as JSON, has exactly the two
required fields with the right types, and that ``selected_features`` is a
lexicographically-sorted list of strings drawn from the allowed feature
names. Does NOT compare against the reference answer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


REQUIRED_FIELDS = {"selected_features", "rmse"}
ALLOWED_FEATURES = {f"x{i}" for i in range(1, 11)}


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

    if "selected_features" in data:
        sf = data["selected_features"]
        if not isinstance(sf, list) or not all(isinstance(x, str) for x in sf):
            errors.append("selected_features must be a list of strings")
        else:
            bad = [x for x in sf if x not in ALLOWED_FEATURES]
            if bad:
                errors.append(f"selected_features contains unknown names: {bad}")
            if sf != sorted(sf):
                errors.append(
                    "selected_features must be sorted in ascending lexicographic order"
                )
            if len(set(sf)) != len(sf):
                errors.append("selected_features contains duplicates")

    if "rmse" in data and not isinstance(data["rmse"], (int, float)):
        errors.append(f"rmse must be a number; got {type(data['rmse']).__name__}")

    if errors:
        for err in errors:
            print(f"FAIL: {err}")
        sys.exit(1)

    print(
        f"OK: result.json has {len(data['selected_features'])} selected features, "
        f"rmse={data['rmse']}"
    )
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
