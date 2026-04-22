#!/usr/bin/env python3
"""Structural verifier for enumeration__nqueens_7.

Checks output/solutions.jsonl:
  - valid JSONL
  - each line is a length-7 permutation of {0..6}
"""

import json
import sys
from pathlib import Path

OUTPUT = Path(__file__).parent / "output" / "solutions.jsonl"
N = 7


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
        if not isinstance(obj, list) or len(obj) != N:
            print(f"FAIL: line {lineno}: expected length-{N} list", file=sys.stderr)
            return 1
        if not all(isinstance(v, int) for v in obj):
            print(f"FAIL: line {lineno}: ints only", file=sys.stderr)
            return 1
        if sorted(obj) != list(range(N)):
            print(f"FAIL: line {lineno}: not a permutation of 0..{N-1}", file=sys.stderr)
            return 1
        n_seen += 1

    print(f"OK: {n_seen} candidate solution(s) with correct schema")
    return 0


if __name__ == "__main__":
    sys.exit(main())
