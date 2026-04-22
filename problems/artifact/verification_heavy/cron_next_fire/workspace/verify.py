#!/usr/bin/env python3
"""Structural verifier for verification_heavy__cron_next_fire."""

import importlib.util
import sys
from datetime import datetime
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

    if not hasattr(mod, "next_fire") or not callable(mod.next_fire):
        print("FAIL: solution.py does not define callable 'next_fire'", file=sys.stderr)
        return 1

    try:
        r = mod.next_fire("* * * * *", datetime(2024, 1, 1, 12, 0))
        if not isinstance(r, datetime):
            print(f"WARN: next_fire returned {type(r).__name__}, expected datetime")
    except Exception as exc:
        print(f"WARN: next_fire raised {type(exc).__name__}: {exc}")

    print("OK: solution.py imports and defines 'next_fire'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
