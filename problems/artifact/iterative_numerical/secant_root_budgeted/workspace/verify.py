#!/usr/bin/env python3
"""Structural verifier for iterative_numerical__secant_root_budgeted."""

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).parent
BRACKETS = HERE / "brackets.json"
OUTPUT = HERE / "output" / "roots.json"


def main() -> int:
    if not OUTPUT.is_file():
        print(f"FAIL: {OUTPUT} not found", file=sys.stderr)
        return 1
    try:
        brackets = json.loads(BRACKETS.read_text())
        out = json.loads(OUTPUT.read_text())
    except Exception as exc:
        print(f"FAIL: could not parse JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(out, dict):
        print("FAIL: output must be a JSON object", file=sys.stderr)
        return 1
    for entry in brackets:
        name = entry["name"]
        a, b = float(entry["a"]), float(entry["b"])
        if name not in out:
            print(f"FAIL: missing root for {name!r}", file=sys.stderr)
            return 1
        v = out[name]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            print(f"FAIL: {name!r} must be a number", file=sys.stderr)
            return 1
        if not math.isfinite(v):
            print(f"FAIL: {name!r} must be finite", file=sys.stderr)
            return 1
        if not (a <= v <= b):
            print(f"FAIL: {name!r}={v} outside bracket [{a},{b}]", file=sys.stderr)
            return 1
    print(f"OK: {len(out)} roots, all inside declared brackets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
