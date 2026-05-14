"""Structural verifier for ``data_science__regression_metrics_grouped_medium``.

Checks ``output/result.json`` exists, parses as JSON, has the right top-level
shape, and that ``per_group`` entries are well-formed and lexicographically
sorted. Does NOT compare against the reference answer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


REQUIRED_TOP = {"per_group", "overall"}
REQUIRED_GROUP_FIELDS = {"group", "n", "rmse", "mae", "r2"}
REQUIRED_OVERALL_FIELDS = {"n", "rmse", "mae", "r2"}


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
    missing = REQUIRED_TOP - keys
    extra = keys - REQUIRED_TOP
    errors: list[str] = []
    if missing:
        errors.append(f"missing top-level field(s): {sorted(missing)}")
    if extra:
        errors.append(f"unexpected top-level field(s): {sorted(extra)}")

    pg = data.get("per_group")
    if not isinstance(pg, list):
        errors.append("per_group must be a list")
    else:
        names = []
        for i, entry in enumerate(pg):
            if not isinstance(entry, dict):
                errors.append(f"per_group[{i}] must be an object")
                continue
            ek = set(entry.keys())
            if ek != REQUIRED_GROUP_FIELDS:
                errors.append(
                    f"per_group[{i}] keys {sorted(ek)} != {sorted(REQUIRED_GROUP_FIELDS)}"
                )
                continue
            if not isinstance(entry["group"], str):
                errors.append(f"per_group[{i}].group must be a string")
            else:
                names.append(entry["group"])
            if not (isinstance(entry["n"], int) and not isinstance(entry["n"], bool)):
                errors.append(f"per_group[{i}].n must be a non-bool integer")
            for fld in ("rmse", "mae", "r2"):
                v = entry[fld]
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    errors.append(f"per_group[{i}].{fld} must be a number")
        if names != sorted(names):
            errors.append("per_group must be sorted ascending by group name")
        if len(set(names)) != len(names):
            errors.append("per_group has duplicate group names")

    ov = data.get("overall")
    if not isinstance(ov, dict):
        errors.append("overall must be an object")
    else:
        ok = set(ov.keys())
        if ok != REQUIRED_OVERALL_FIELDS:
            errors.append(
                f"overall keys {sorted(ok)} != {sorted(REQUIRED_OVERALL_FIELDS)}"
            )
        else:
            if not (isinstance(ov["n"], int) and not isinstance(ov["n"], bool)):
                errors.append("overall.n must be a non-bool integer")
            for fld in ("rmse", "mae", "r2"):
                v = ov[fld]
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    errors.append(f"overall.{fld} must be a number")

    if errors:
        for err in errors:
            print(f"FAIL: {err}")
        sys.exit(1)

    print(
        f"OK: per_group has {len(data['per_group'])} entries, overall.n={data['overall']['n']}"
    )
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
