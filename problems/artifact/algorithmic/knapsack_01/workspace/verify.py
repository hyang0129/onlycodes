#!/usr/bin/env python3
"""Structural verifier for algorithmic__knapsack_01."""

import json
import sys
from pathlib import Path

PARCELS = Path(__file__).parent / "parcels.json"
OUTPUT = Path(__file__).parent / "output" / "pack.json"


def main() -> int:
    if not PARCELS.is_file():
        print(f"FAIL: parcels.json not found at {PARCELS}", file=sys.stderr)
        return 1
    data = json.loads(PARCELS.read_text())
    n = len(data["items"])
    capacity = data["capacity"]

    if not OUTPUT.is_file():
        print(f"FAIL: output file not found: {OUTPUT}", file=sys.stderr)
        return 1

    try:
        out = json.loads(OUTPUT.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: could not parse output JSON: {exc}", file=sys.stderr)
        return 1

    if not isinstance(out, dict):
        print("FAIL: output must be a JSON object", file=sys.stderr)
        return 1

    if "total_value" not in out:
        print("FAIL: missing required key 'total_value'", file=sys.stderr)
        return 1

    tv = out["total_value"]
    if isinstance(tv, bool) or not isinstance(tv, int):
        print(f"FAIL: total_value must be an integer, got {type(tv).__name__}", file=sys.stderr)
        return 1
    if tv < 0:
        print(f"FAIL: total_value must be non-negative, got {tv}", file=sys.stderr)
        return 1

    if "chosen_ids" in out:
        ids = out["chosen_ids"]
        if not isinstance(ids, list) or any(not isinstance(i, int) or isinstance(i, bool) for i in ids):
            print("FAIL: chosen_ids must be a list of integers", file=sys.stderr)
            return 1
        if len(set(ids)) != len(ids):
            print("FAIL: chosen_ids contains duplicates", file=sys.stderr)
            return 1
        if any(i < 0 or i >= n for i in ids):
            print(f"FAIL: chosen_ids contains out-of-range id (valid: 0..{n-1})", file=sys.stderr)
            return 1
        by_id = {it["id"]: it for it in data["items"]}
        w = sum(by_id[i]["weight"] for i in ids)
        if w > capacity:
            print(f"FAIL: chosen weight {w} exceeds capacity {capacity}", file=sys.stderr)
            return 1

    print(f"OK: total_value={tv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
