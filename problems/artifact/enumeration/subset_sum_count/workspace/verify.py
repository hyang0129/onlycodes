#!/usr/bin/env python3
"""Structural verifier for enumeration__subset_sum_count.

Checks output/subsets.jsonl:
  - valid JSONL
  - each line is a sorted list of ints in range [0, n_amounts)
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
OUTPUT = HERE / "output" / "subsets.jsonl"
AMOUNTS_FILE = HERE / "amounts.json"


def main() -> int:
    if not AMOUNTS_FILE.is_file():
        print(f"FAIL: {AMOUNTS_FILE} missing", file=sys.stderr)
        return 1
    n = len(json.loads(AMOUNTS_FILE.read_text())["amounts"])

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
        if not isinstance(obj, list) or not all(isinstance(v, int) for v in obj):
            print(f"FAIL: line {lineno}: expected list of ints", file=sys.stderr)
            return 1
        if any(v < 0 or v >= n for v in obj):
            print(f"FAIL: line {lineno}: index out of range [0,{n})", file=sys.stderr)
            return 1
        if obj != sorted(obj):
            print(f"FAIL: line {lineno}: indices must be sorted ascending", file=sys.stderr)
            return 1
        if len(set(obj)) != len(obj):
            print(f"FAIL: line {lineno}: duplicate index within subset", file=sys.stderr)
            return 1
        n_seen += 1

    print(f"OK: {n_seen} candidate subset(s) with correct schema")
    return 0


if __name__ == "__main__":
    sys.exit(main())
