#!/usr/bin/env python3
"""Structural verifier for iterative_numerical__hparam_search."""

import json
import sys
from pathlib import Path

OUTPUT = Path(__file__).parent / "output" / "result.json"


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
    for key in ("learning_rate", "hidden_size", "dropout"):
        if key not in out:
            print(f"FAIL: missing key '{key}'", file=sys.stderr)
            return 1
    print(f"OK: lr={out['learning_rate']}, hs={out['hidden_size']}, dropout={out['dropout']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
