#!/usr/bin/env python3
"""Structural verifier for verification_heavy__expression_evaluator."""

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

    if not hasattr(mod, "evaluate") or not callable(mod.evaluate):
        print("FAIL: solution.py does not define callable 'evaluate'", file=sys.stderr)
        return 1

    try:
        v = mod.evaluate("1+2")
        if not isinstance(v, float):
            print(f"WARN: evaluate('1+2') returned {type(v).__name__}, expected float")
    except Exception as exc:
        print(f"WARN: evaluate('1+2') raised {type(exc).__name__}: {exc}")

    print("OK: solution.py imports and defines 'evaluate'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
