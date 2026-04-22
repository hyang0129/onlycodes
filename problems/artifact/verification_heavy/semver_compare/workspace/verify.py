#!/usr/bin/env python3
"""Structural verifier for verification_heavy__semver_compare."""

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

    if not hasattr(mod, "compare_semver"):
        print("FAIL: solution.py does not define 'compare_semver'", file=sys.stderr)
        return 1

    if not callable(mod.compare_semver):
        print("FAIL: 'compare_semver' is not callable", file=sys.stderr)
        return 1

    try:
        r = mod.compare_semver("1.0.0", "1.0.0")
        if r != 0:
            print(f"WARN: compare_semver('1.0.0','1.0.0') returned {r}, expected 0")
    except Exception as exc:
        print(f"WARN: compare_semver raised {type(exc).__name__}: {exc}")

    print("OK: solution.py imports and defines 'compare_semver'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
