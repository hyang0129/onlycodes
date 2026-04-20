#!/usr/bin/env python3
"""Structural verifier for stateful_reasoning__upgrade_impact.

Checks output/conflicts.jsonl:
  - valid JSONL
  - each line is a JSON object with a "package" key (string)
"""

import json
import sys
from pathlib import Path

OUTPUT = Path(__file__).parent / "output" / "conflicts.jsonl"


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
        if not isinstance(obj, dict) or "package" not in obj:
            print(f"FAIL: line {lineno}: expected JSON object with 'package' key", file=sys.stderr)
            return 1
        pkg = obj["package"]
        if pkg in seen:
            print(f"WARN: line {lineno}: duplicate package {pkg!r}")
        seen.add(pkg)
        count += 1

    if count == 0:
        print("FAIL: no entries in output", file=sys.stderr)
        return 1

    print(f"OK: {count} conflict(s) listed with correct schema")
    return 0


if __name__ == "__main__":
    sys.exit(main())
