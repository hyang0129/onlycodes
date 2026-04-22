#!/usr/bin/env python3
"""Structural verifier for enumeration__permutations_fixed_points.

Checks output/perms.jsonl:
  - valid JSONL
  - each line is a list of 5 ints that is a permutation of {0..4}

Does NOT check the "exactly 2 fixed points" constraint or completeness —
those are the hidden grader's responsibility.
"""

import json
import sys
from pathlib import Path

OUTPUT = Path(__file__).parent / "output" / "perms.jsonl"


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
        if not isinstance(obj, list) or len(obj) != 5:
            print(f"FAIL: line {lineno}: expected list of length 5", file=sys.stderr)
            return 1
        if not all(isinstance(v, int) for v in obj):
            print(f"FAIL: line {lineno}: all entries must be ints", file=sys.stderr)
            return 1
        if sorted(obj) != [0, 1, 2, 3, 4]:
            print(f"FAIL: line {lineno}: not a permutation of 0..4", file=sys.stderr)
            return 1
        n_seen += 1

    if n_seen == 0:
        print("FAIL: no permutations in output", file=sys.stderr)
        return 1

    print(f"OK: {n_seen} candidate permutation(s) with correct schema")
    return 0


if __name__ == "__main__":
    sys.exit(main())
