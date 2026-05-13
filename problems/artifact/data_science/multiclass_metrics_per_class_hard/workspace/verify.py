"""Structural verifier for ``data_science__multiclass_metrics_per_class_hard``.

Checks ``output/result.json`` exists, parses as JSON, has the right top-level
shape, and that ``per_class`` entries are well-formed and sorted by class.
Does NOT compare against the reference answer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


REQUIRED_TOP = {"per_class", "macro_avg", "weighted_avg", "accuracy"}
REQUIRED_PER_CLASS = {"class", "support", "precision", "recall", "f1"}
REQUIRED_AVG = {"precision", "recall", "f1"}


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
    errors: list[str] = []
    missing = REQUIRED_TOP - keys
    extra = keys - REQUIRED_TOP
    if missing:
        errors.append(f"missing top-level field(s): {sorted(missing)}")
    if extra:
        errors.append(f"unexpected top-level field(s): {sorted(extra)}")

    pc = data.get("per_class")
    if not isinstance(pc, list):
        errors.append("per_class must be a list")
    else:
        classes = []
        for i, entry in enumerate(pc):
            if not isinstance(entry, dict):
                errors.append(f"per_class[{i}] must be an object")
                continue
            ek = set(entry.keys())
            if ek != REQUIRED_PER_CLASS:
                errors.append(
                    f"per_class[{i}] keys {sorted(ek)} != {sorted(REQUIRED_PER_CLASS)}"
                )
                continue
            if not (isinstance(entry["class"], int) and not isinstance(entry["class"], bool)):
                errors.append(f"per_class[{i}].class must be a non-bool integer")
            else:
                classes.append(entry["class"])
            if not (isinstance(entry["support"], int) and not isinstance(entry["support"], bool)):
                errors.append(f"per_class[{i}].support must be a non-bool integer")
            for fld in ("precision", "recall", "f1"):
                v = entry[fld]
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    errors.append(f"per_class[{i}].{fld} must be a number")
        if classes != sorted(classes):
            errors.append("per_class must be sorted ascending by class")
        if len(set(classes)) != len(classes):
            errors.append("per_class contains duplicate class labels")

    for avg_key in ("macro_avg", "weighted_avg"):
        avg = data.get(avg_key)
        if not isinstance(avg, dict):
            errors.append(f"{avg_key} must be an object")
            continue
        ak = set(avg.keys())
        if ak != REQUIRED_AVG:
            errors.append(f"{avg_key} keys {sorted(ak)} != {sorted(REQUIRED_AVG)}")
            continue
        for fld in REQUIRED_AVG:
            v = avg[fld]
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                errors.append(f"{avg_key}.{fld} must be a number")

    acc = data.get("accuracy")
    if acc is not None and (not isinstance(acc, (int, float)) or isinstance(acc, bool)):
        errors.append(f"accuracy must be a number; got {type(acc).__name__}")

    if errors:
        for err in errors:
            print(f"FAIL: {err}")
        sys.exit(1)

    print(
        f"OK: result.json has {len(data['per_class'])} per-class entries, "
        f"accuracy={data['accuracy']}"
    )
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
