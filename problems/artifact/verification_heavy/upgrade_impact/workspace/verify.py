#!/usr/bin/env python3
"""Structural verifier for verification_heavy__upgrade_impact.

Checks output/conflicts.jsonl:
  - valid JSONL
  - each line is a JSON object with a "package" key (string)

Usage:
  python verify.py [scratch_dir]

If ``scratch_dir`` is omitted, the script falls back to the directory that
contains this file (i.e. the workspace copy), which lets agents invoke it
directly as ``python verify.py`` from within the scratch directory.

Issue #185: grader contract requires accepting ``scratch_dir`` as ``argv[1]``
so the harness can invoke the verifier from outside the workspace directory.
"""

import json
import sys
from pathlib import Path

# Accept scratch_dir from argv[1] (grader contract); fall back to __file__'s
# parent so the script still works when invoked without arguments.
_scratch = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
OUTPUT = _scratch / "output" / "conflicts.jsonl"


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
