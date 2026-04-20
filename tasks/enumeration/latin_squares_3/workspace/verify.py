#!/usr/bin/env python3
"""Structural verifier for enumeration__latin_squares_3.

Checks output/latin_squares.jsonl:
  - valid JSONL
  - each line is a 3×3 integer matrix
  - each row contains only values from {1, 2, 3}

Does NOT check completeness or Latin square validity — that is the hidden grader.
"""

import json
import sys
from pathlib import Path

OUTPUT = Path(__file__).parent / "output" / "latin_squares.jsonl"


def main() -> int:
    if not OUTPUT.is_file():
        print(f"FAIL: {OUTPUT} not found", file=sys.stderr)
        return 1

    rows_seen = 0
    for lineno, line in enumerate(OUTPUT.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"FAIL: line {lineno}: JSON error: {exc.msg}", file=sys.stderr)
            return 1
        if not isinstance(obj, list) or len(obj) != 3:
            print(f"FAIL: line {lineno}: expected list of 3 rows", file=sys.stderr)
            return 1
        for ri, row in enumerate(obj):
            if not isinstance(row, list) or len(row) != 3:
                print(f"FAIL: line {lineno} row {ri}: expected list of 3 ints", file=sys.stderr)
                return 1
            if not all(isinstance(v, int) and 1 <= v <= 3 for v in row):
                print(f"FAIL: line {lineno} row {ri}: values must be ints in {{1,2,3}}", file=sys.stderr)
                return 1
        rows_seen += 1

    if rows_seen == 0:
        print("FAIL: no squares found in output", file=sys.stderr)
        return 1

    print(f"OK: {rows_seen} candidate square(s) with correct schema")
    return 0


if __name__ == "__main__":
    sys.exit(main())
