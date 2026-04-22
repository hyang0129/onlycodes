#!/usr/bin/env python3
"""Structural verifier for verification_heavy__json_pointer_rfc6901."""

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

    missing = [name for name in ("resolve", "set_at") if not callable(getattr(mod, name, None))]
    if missing:
        print(f"FAIL: solution.py missing callable(s): {missing}", file=sys.stderr)
        return 1

    try:
        doc = {"a": [1, 2]}
        if mod.resolve(doc, "/a/0") != 1:
            print("WARN: resolve(doc, '/a/0') returned unexpected value")
        mod.set_at(doc, "/a/0", 99)
        if doc["a"][0] != 99:
            print("WARN: set_at did not mutate doc as expected")
    except Exception as exc:
        print(f"WARN: smoke test raised {type(exc).__name__}: {exc}")

    print("OK: solution.py imports and defines 'resolve' and 'set_at'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
