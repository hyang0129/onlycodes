#!/usr/bin/env python3
"""Structural verifier for enumeration__sudoku_row_completions.

Checks output/completions.jsonl:
  - valid JSONL
  - each line is a length-9 permutation of {1..9}
"""

import json
import sys
from pathlib import Path

OUTPUT = Path(__file__).parent / "output" / "completions.jsonl"


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
        if not isinstance(obj, list) or len(obj) != 9:
            print(f"FAIL: line {lineno}: expected length-9 list", file=sys.stderr)
            return 1
        if not all(isinstance(v, int) for v in obj):
            print(f"FAIL: line {lineno}: all entries must be ints", file=sys.stderr)
            return 1
        if sorted(obj) != list(range(1, 10)):
            print(f"FAIL: line {lineno}: not a permutation of 1..9", file=sys.stderr)
            return 1
        n_seen += 1

    print(f"OK: {n_seen} candidate completion(s) with correct schema")
    return 0


if __name__ == "__main__":
    sys.exit(main())
