#!/usr/bin/env python3
"""Structural verifier for iterative_numerical__newton_sqrt."""

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).parent
INPUT = HERE / "inputs.json"
OUTPUT = HERE / "output" / "roots.json"


def main() -> int:
    if not OUTPUT.is_file():
        print(f"FAIL: {OUTPUT} not found", file=sys.stderr)
        return 1
    try:
        inp = json.loads(INPUT.read_text())
        out = json.loads(OUTPUT.read_text())
    except Exception as exc:
        print(f"FAIL: could not parse JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(out, dict):
        print("FAIL: output must be a JSON object", file=sys.stderr)
        return 1
    for k in inp:
        if k not in out:
            print(f"FAIL: missing id {k!r}", file=sys.stderr)
            return 1
        v = out[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            print(f"FAIL: value for {k!r} must be a number", file=sys.stderr)
            return 1
        if not math.isfinite(v) or v < 0.0:
            print(f"FAIL: value for {k!r} must be finite and non-negative",
                  file=sys.stderr)
            return 1
    print(f"OK: {len(out)} roots covering all {len(inp)} input ids")
    return 0


if __name__ == "__main__":
    sys.exit(main())
