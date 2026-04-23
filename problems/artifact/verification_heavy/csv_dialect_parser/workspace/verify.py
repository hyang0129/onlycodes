#!/usr/bin/env python3
"""Structural verifier for verification_heavy__csv_dialect_parser.

Checks that output/solution.py:
  - exists and is valid Python
  - defines a callable named 'parse_csv_line'
  - accepts a string argument (basic signature check)

Does NOT run the hidden property suite.
"""

import importlib.util
import sys
from pathlib import Path

OUTPUT = Path(__file__).parent / "output" / "solution.py"


def main() -> int:
    if not OUTPUT.is_file():
        print(f"FAIL: output/solution.py not found at {OUTPUT}", file=sys.stderr)
        return 1

    spec = importlib.util.spec_from_file_location("agent_solution", OUTPUT)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:
        print(f"FAIL: could not import solution.py: {exc}", file=sys.stderr)
        return 1

    if not hasattr(mod, "parse_csv_line"):
        print("FAIL: solution.py does not define 'parse_csv_line'", file=sys.stderr)
        return 1

    fn = mod.parse_csv_line
    if not callable(fn):
        print("FAIL: 'parse_csv_line' is not callable", file=sys.stderr)
        return 1

    try:
        fn("a,b,c")
    except Exception as exc:
        print(f"WARN: parse_csv_line('a,b,c') raised {type(exc).__name__}: {exc}")

    print("OK: solution.py imports and defines 'parse_csv_line'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
