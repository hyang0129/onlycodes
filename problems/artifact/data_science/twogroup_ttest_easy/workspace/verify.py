"""Structural verifier for ``data_science__twogroup_ttest_easy``.

Checks ``output/result.json`` exists, parses as JSON, has the right keys
and types. Does NOT compare against the reference answer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


REQUIRED_INT_FIELDS = {"n_control", "n_treatment"}
REQUIRED_FLOAT_FIELDS = {"mean_control", "mean_treatment", "statistic", "pvalue"}
REQUIRED_BOOL_FIELDS = {"reject_null"}
REQUIRED_FIELDS = REQUIRED_INT_FIELDS | REQUIRED_FLOAT_FIELDS | REQUIRED_BOOL_FIELDS


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

    for f in REQUIRED_INT_FIELDS:
        if f in data:
            v = data[f]
            if not isinstance(v, int) or isinstance(v, bool):
                errors.append(f"{f} must be a non-bool integer; got {type(v).__name__}")
    for f in REQUIRED_FLOAT_FIELDS:
        if f in data:
            v = data[f]
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                errors.append(f"{f} must be a number; got {type(v).__name__}")
    for f in REQUIRED_BOOL_FIELDS:
        if f in data:
            v = data[f]
            if not isinstance(v, bool):
                errors.append(f"{f} must be a boolean; got {type(v).__name__}")

    if errors:
        for err in errors:
            print(f"FAIL: {err}")
        sys.exit(1)

    print(
        f"OK: result.json has n_control={data['n_control']}, n_treatment={data['n_treatment']}, "
        f"statistic={data['statistic']}, pvalue={data['pvalue']}, reject_null={data['reject_null']}"
    )
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
