#!/usr/bin/env python3
"""Structural verifier for algorithmic__coin_change_min.

Checks output/answer.json has the correct shape:
  - JSON object
  - "min_coins" key with an integer value (>= -1, != 0 only if amount > 0)

Does NOT check optimality — that is the hidden grader's job.
"""

import json
import sys
from pathlib import Path

REQUEST_FILE = Path(__file__).parent / "request.json"
OUTPUT_FILE = Path(__file__).parent / "output" / "answer.json"


def main() -> int:
    if not REQUEST_FILE.is_file():
        print(f"FAIL: request.json not found at {REQUEST_FILE}", file=sys.stderr)
        return 1

    if not OUTPUT_FILE.is_file():
        print(f"FAIL: output file not found: {OUTPUT_FILE}", file=sys.stderr)
        return 1

    try:
        out = json.loads(OUTPUT_FILE.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: could not parse output JSON: {exc}", file=sys.stderr)
        return 1

    if not isinstance(out, dict):
        print("FAIL: output must be a JSON object", file=sys.stderr)
        return 1

    if "min_coins" not in out:
        print("FAIL: missing required key 'min_coins'", file=sys.stderr)
        return 1

    mc = out["min_coins"]
    if isinstance(mc, bool) or not isinstance(mc, int):
        print(f"FAIL: min_coins must be an integer, got {type(mc).__name__}", file=sys.stderr)
        return 1

    if mc < -1:
        print(f"FAIL: min_coins must be >= -1, got {mc}", file=sys.stderr)
        return 1

    print(f"OK: min_coins={mc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
