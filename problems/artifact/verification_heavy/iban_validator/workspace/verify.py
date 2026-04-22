#!/usr/bin/env python3
"""Structural verifier for verification_heavy__iban_validator."""

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

    if not hasattr(mod, "validate_iban") or not callable(mod.validate_iban):
        print("FAIL: solution.py does not define callable 'validate_iban'", file=sys.stderr)
        return 1

    try:
        r = mod.validate_iban("DE89370400440532013000")
        if r is not True:
            print(f"WARN: validate_iban returned {r!r}, expected True")
    except Exception as exc:
        print(f"WARN: validate_iban raised {type(exc).__name__}: {exc}")

    print("OK: solution.py imports and defines 'validate_iban'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
