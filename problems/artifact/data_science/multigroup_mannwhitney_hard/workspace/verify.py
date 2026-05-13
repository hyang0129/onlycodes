"""Structural verifier for ``data_science__multigroup_mannwhitney_hard``.

Checks ``output/result.json`` exists, parses as JSON, and has the right
top-level shape, with ``pairs`` well-formed and sorted by (group_a,
group_b) ascending. Does NOT compare against the reference answer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


REQUIRED_TOP = {"alpha", "alpha_corrected", "n_pairs", "pairs"}
REQUIRED_PAIR_FIELDS = {
    "group_a", "group_b", "n_a", "n_b", "U", "pvalue", "reject_null",
}


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

    for fld in ("alpha", "alpha_corrected"):
        if fld in data:
            v = data[fld]
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                errors.append(f"{fld} must be a number")
    if "n_pairs" in data:
        v = data["n_pairs"]
        if not isinstance(v, int) or isinstance(v, bool):
            errors.append("n_pairs must be a non-bool integer")

    pairs = data.get("pairs")
    if not isinstance(pairs, list):
        errors.append("pairs must be a list")
    else:
        seen: list[tuple[str, str]] = []
        for i, entry in enumerate(pairs):
            if not isinstance(entry, dict):
                errors.append(f"pairs[{i}] must be an object")
                continue
            ek = set(entry.keys())
            if ek != REQUIRED_PAIR_FIELDS:
                errors.append(
                    f"pairs[{i}] keys {sorted(ek)} != {sorted(REQUIRED_PAIR_FIELDS)}"
                )
                continue
            ga, gb = entry["group_a"], entry["group_b"]
            if not (isinstance(ga, str) and isinstance(gb, str)):
                errors.append(f"pairs[{i}].group_a/group_b must be strings")
            else:
                if not (ga < gb):
                    errors.append(
                        f"pairs[{i}] must have group_a < group_b (got {ga!r}, {gb!r})"
                    )
                seen.append((ga, gb))
            for fld in ("n_a", "n_b"):
                if not isinstance(entry[fld], int) or isinstance(entry[fld], bool):
                    errors.append(f"pairs[{i}].{fld} must be a non-bool integer")
            for fld in ("U", "pvalue"):
                v = entry[fld]
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    errors.append(f"pairs[{i}].{fld} must be a number")
            if not isinstance(entry["reject_null"], bool):
                errors.append(f"pairs[{i}].reject_null must be a boolean")
        if seen != sorted(seen):
            errors.append("pairs must be sorted ascending by (group_a, group_b)")
        if len(set(seen)) != len(seen):
            errors.append("pairs contains duplicate (group_a, group_b) entries")

    if errors:
        for err in errors:
            print(f"FAIL: {err}")
        sys.exit(1)

    print(
        f"OK: pairs has {len(data['pairs'])} entries; "
        f"alpha_corrected={data['alpha_corrected']}"
    )
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
