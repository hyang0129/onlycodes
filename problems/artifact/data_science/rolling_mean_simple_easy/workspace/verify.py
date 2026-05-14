"""Structural verifier for ``data_science__rolling_mean_simple_easy``.

Checks ``output/result.json`` exists, parses as JSON, has the right top-
level shape, and that ``rolling`` is a list of well-formed entries
sorted ascending by ``t``. Does NOT compare against the reference answer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


REQUIRED_TOP = {"rolling"}
REQUIRED_ENTRY = {"t", "rolling_mean"}
WINDOW = 7


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

    rolling = data.get("rolling")
    if not isinstance(rolling, list):
        errors.append("rolling must be a list")
    else:
        ts: list[int] = []
        for i, entry in enumerate(rolling):
            if not isinstance(entry, dict):
                errors.append(f"rolling[{i}] must be an object")
                continue
            ek = set(entry.keys())
            if ek != REQUIRED_ENTRY:
                errors.append(f"rolling[{i}] keys {sorted(ek)} != {sorted(REQUIRED_ENTRY)}")
                continue
            t = entry["t"]
            v = entry["rolling_mean"]
            if not isinstance(t, int) or isinstance(t, bool):
                errors.append(f"rolling[{i}].t must be a non-bool integer")
                continue
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                errors.append(f"rolling[{i}].rolling_mean must be a number")
            ts.append(t)
        if ts != sorted(ts):
            errors.append("rolling entries must be sorted ascending by t")
        if len(set(ts)) != len(ts):
            errors.append("rolling has duplicate t values")
        if any(t < WINDOW - 1 for t in ts):
            errors.append(
                f"rolling contains t < {WINDOW - 1} (incomplete-window rows must not be emitted)"
            )

    if errors:
        for err in errors:
            print(f"FAIL: {err}")
        sys.exit(1)

    print(f"OK: result.json emits {len(data['rolling'])} rolling-mean row(s)")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
