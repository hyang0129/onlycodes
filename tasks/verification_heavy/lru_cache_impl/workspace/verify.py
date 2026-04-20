#!/usr/bin/env python3
"""Structural verifier for verification_heavy__lru_cache_impl.

Checks that output/lru_cache.py:
  - exists and is valid Python
  - defines a class named 'LRUCache'
  - instances expose callable 'get' and 'put' methods

Does NOT run the hidden property suite.
"""

import importlib.util
import sys
from pathlib import Path

OUTPUT = Path(__file__).parent / "output" / "lru_cache.py"


def main() -> int:
    if not OUTPUT.is_file():
        print(f"FAIL: output/lru_cache.py not found at {OUTPUT}", file=sys.stderr)
        return 1

    spec = importlib.util.spec_from_file_location("agent_lru", OUTPUT)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:
        print(f"FAIL: could not import lru_cache.py: {exc}", file=sys.stderr)
        return 1

    if not hasattr(mod, "LRUCache"):
        print("FAIL: lru_cache.py does not define 'LRUCache'", file=sys.stderr)
        return 1

    try:
        cache = mod.LRUCache(2)
    except Exception as exc:
        print(f"FAIL: LRUCache(2) raised {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    for method in ("get", "put"):
        if not callable(getattr(cache, method, None)):
            print(f"FAIL: LRUCache instance missing callable method '{method}'", file=sys.stderr)
            return 1

    print("OK: lru_cache.py defines LRUCache with get/put methods")
    return 0


if __name__ == "__main__":
    sys.exit(main())
