#!/usr/bin/env python3
"""Structural verifier for enumeration__integer_partitions_15.

Checks output/partitions.jsonl:
  - valid JSONL
  - each line is a non-increasing list of positive ints summing to 15
"""

import json
import sys
from pathlib import Path

OUTPUT = Path(__file__).parent / "output" / "partitions.jsonl"
TARGET = 15


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
        if not isinstance(obj, list) or not obj:
            print(f"FAIL: line {lineno}: expected non-empty list", file=sys.stderr)
            return 1
        if not all(isinstance(v, int) and v > 0 for v in obj):
            print(f"FAIL: line {lineno}: all entries must be positive ints", file=sys.stderr)
            return 1
        if sum(obj) != TARGET:
            print(f"FAIL: line {lineno}: entries sum to {sum(obj)}, not {TARGET}", file=sys.stderr)
            return 1
        if obj != sorted(obj, reverse=True):
            print(f"FAIL: line {lineno}: entries must be non-increasing", file=sys.stderr)
            return 1
        n_seen += 1

    print(f"OK: {n_seen} candidate partition(s) with correct schema")
    return 0


if __name__ == "__main__":
    sys.exit(main())
