#!/usr/bin/env python3
"""Structural verifier for stateful_reasoning__unreachable_functions.

Checks output/unreachable.jsonl:
  - valid JSONL
  - each line is a JSON object with a "function" key (string)
"""

import json
import sys
from pathlib import Path

OUTPUT = Path(__file__).parent / "output" / "unreachable.jsonl"


def main() -> int:
    if not OUTPUT.is_file():
        print(f"FAIL: {OUTPUT} not found", file=sys.stderr)
        return 1

    count = 0
    seen = set()
    for lineno, line in enumerate(OUTPUT.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"FAIL: line {lineno}: JSON error: {exc.msg}", file=sys.stderr)
            return 1
        if not isinstance(obj, dict):
            print(f"FAIL: line {lineno}: expected JSON object", file=sys.stderr)
            return 1
        if "function" not in obj:
            print(f"FAIL: line {lineno}: missing 'function' key", file=sys.stderr)
            return 1
        fname = obj["function"]
        if fname in seen:
            print(f"WARN: line {lineno}: duplicate function name {fname!r}")
        seen.add(fname)
        count += 1

    if count == 0:
        print("FAIL: no entries in output", file=sys.stderr)
        return 1

    print(f"OK: {count} function(s) listed with correct schema")
    return 0


if __name__ == "__main__":
    sys.exit(main())
