"""Structural verifier for ``data_science__cohort_ttest_medium``.

Checks ``output/result.json`` exists, parses as JSON, has the right top-
level shape, and that ``per_cohort`` entries are well-formed and sorted
lexicographically. Does NOT compare against the reference answer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


REQUIRED_TOP = {"per_cohort", "overall"}
REQUIRED_COHORT_FIELDS = {
    "cohort", "n_pairs", "mean_diff", "statistic", "pvalue", "reject_null",
}
REQUIRED_OVERALL_FIELDS = {
    "n_pairs", "mean_diff", "statistic", "pvalue", "reject_null",
}


def _check_entry(entry: object, scope: str, required: set[str], errors: list[str]) -> None:
    if not isinstance(entry, dict):
        errors.append(f"{scope} must be an object")
        return
    ek = set(entry.keys())
    if ek != required:
        errors.append(f"{scope} keys {sorted(ek)} != {sorted(required)}")
        return
    if "cohort" in required:
        if not isinstance(entry["cohort"], str):
            errors.append(f"{scope}.cohort must be a string")
    if not isinstance(entry["n_pairs"], int) or isinstance(entry["n_pairs"], bool):
        errors.append(f"{scope}.n_pairs must be a non-bool integer")
    for fld in ("mean_diff", "statistic", "pvalue"):
        v = entry[fld]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            errors.append(f"{scope}.{fld} must be a number")
    if not isinstance(entry["reject_null"], bool):
        errors.append(f"{scope}.reject_null must be a boolean")


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

    pc = data.get("per_cohort")
    if not isinstance(pc, list):
        errors.append("per_cohort must be a list")
    else:
        names: list[str] = []
        for i, entry in enumerate(pc):
            _check_entry(entry, f"per_cohort[{i}]", REQUIRED_COHORT_FIELDS, errors)
            if isinstance(entry, dict) and isinstance(entry.get("cohort"), str):
                names.append(entry["cohort"])
        if names != sorted(names):
            errors.append("per_cohort must be sorted ascending by cohort name")
        if len(set(names)) != len(names):
            errors.append("per_cohort contains duplicate cohort names")

    if "overall" in data:
        _check_entry(data["overall"], "overall", REQUIRED_OVERALL_FIELDS, errors)

    if errors:
        for err in errors:
            print(f"FAIL: {err}")
        sys.exit(1)

    print(
        f"OK: per_cohort has {len(data['per_cohort'])} entries, overall.n_pairs={data['overall']['n_pairs']}"
    )
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
