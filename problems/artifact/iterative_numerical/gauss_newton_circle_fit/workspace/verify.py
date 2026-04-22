#!/usr/bin/env python3
"""Structural verifier for iterative_numerical__gauss_newton_circle_fit."""

import json
import math
import sys
from pathlib import Path

OUTPUT = Path(__file__).parent / "output" / "circle.json"


def main() -> int:
    if not OUTPUT.is_file():
        print(f"FAIL: {OUTPUT} not found", file=sys.stderr)
        return 1
    try:
        out = json.loads(OUTPUT.read_text())
    except Exception as exc:
        print(f"FAIL: could not parse JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(out, dict):
        print("FAIL: output must be a JSON object", file=sys.stderr)
        return 1
    for key in ("cx", "cy", "r"):
        if key not in out:
            print(f"FAIL: missing key {key!r}", file=sys.stderr)
            return 1
        v = out[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            print(f"FAIL: {key!r} must be a number", file=sys.stderr)
            return 1
        if not math.isfinite(v):
            print(f"FAIL: {key!r} must be finite", file=sys.stderr)
            return 1
    if out["r"] <= 0:
        print("FAIL: r must be > 0", file=sys.stderr)
        return 1
    print(f"OK: cx={out['cx']}, cy={out['cy']}, r={out['r']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
