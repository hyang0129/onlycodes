#!/usr/bin/env python3
"""Structural verifier for enumeration__binary_strings_no_run.

Checks output/strings.jsonl:
  - valid JSONL
  - each line is a JSON string of length 10 over {'0','1'}
"""

import json
import sys
from pathlib import Path

OUTPUT = Path(__file__).parent / "output" / "strings.jsonl"
LENGTH = 10


def main() -> int:
    if not OUTPUT.is_file():
        print(f"FAIL: {OUTPUT} not found", file=sys.stderr)
        return 1

    n_seen = 0
    for lineno, line in enumerate(OUTPUT.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"FAIL: line {lineno}: JSON error: {exc.msg}", file=sys.stderr)
            return 1
        if not isinstance(obj, str) or len(obj) != LENGTH:
            print(f"FAIL: line {lineno}: expected length-{LENGTH} string", file=sys.stderr)
            return 1
        if any(ch not in "01" for ch in obj):
            print(f"FAIL: line {lineno}: only '0' and '1' allowed", file=sys.stderr)
            return 1
        n_seen += 1

    print(f"OK: {n_seen} candidate string(s) with correct schema")
    return 0


if __name__ == "__main__":
    sys.exit(main())
