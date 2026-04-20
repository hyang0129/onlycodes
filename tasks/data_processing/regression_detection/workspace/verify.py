#!/usr/bin/env python3
"""Structural verifier for data_processing__regression_detection.

Checks output/regressions.jsonl has the right shape: exactly 3 JSONL rows,
each with exactly the keys "endpoint" (string) and "regression_score" (number).

Does NOT check correctness — that's the hidden grader's job.
Run after producing the artifact to catch obvious formatting errors early.
"""

import json
import sys
from pathlib import Path

OUTPUT = Path(__file__).parent / "output" / "regressions.jsonl"

REQUIRED_KEYS = {"endpoint", "regression_score"}


def main() -> int:
    if not OUTPUT.is_file():
        print(f"FAIL: output file not found: {OUTPUT}", file=sys.stderr)
        return 1

    rows = []
    for lineno, line in enumerate(OUTPUT.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"FAIL: line {lineno}: JSON parse error: {exc.msg}", file=sys.stderr)
            return 1
        if not isinstance(row, dict):
            print(f"FAIL: line {lineno}: not a JSON object", file=sys.stderr)
            return 1
        keys = set(row.keys())
        if keys != REQUIRED_KEYS:
            missing = REQUIRED_KEYS - keys
            extra = keys - REQUIRED_KEYS
            bits = []
            if missing:
                bits.append(f"missing keys: {sorted(missing)}")
            if extra:
                bits.append(f"unexpected keys: {sorted(extra)}")
            print(f"FAIL: line {lineno}: {'; '.join(bits)}", file=sys.stderr)
            return 1
        if not isinstance(row["endpoint"], str):
            print(f"FAIL: line {lineno}: endpoint must be a string", file=sys.stderr)
            return 1
        score = row["regression_score"]
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            print(f"FAIL: line {lineno}: regression_score must be a number", file=sys.stderr)
            return 1
        rows.append(row)

    if len(rows) != 3:
        print(f"FAIL: expected exactly 3 rows, got {len(rows)}", file=sys.stderr)
        return 1

    print(f"OK: {len(rows)} rows, correct schema")
    return 0


if __name__ == "__main__":
    sys.exit(main())
