#!/usr/bin/env python3
"""Structural verifier for algorithmic__bin_packing_first_fit_optimal."""

import json
import sys
from pathlib import Path

PARCELS = Path(__file__).parent / "parcels.json"
OUTPUT = Path(__file__).parent / "output" / "bins.json"


def main() -> int:
    if not PARCELS.is_file():
        print(f"FAIL: parcels.json not found at {PARCELS}", file=sys.stderr)
        return 1
    data = json.loads(PARCELS.read_text())
    weights = data["weights"]
    capacity = data["capacity"]
    n = len(weights)

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

    if "num_bins" not in out:
        print("FAIL: missing required key 'num_bins'", file=sys.stderr)
        return 1

    nb = out["num_bins"]
    if isinstance(nb, bool) or not isinstance(nb, int) or nb <= 0:
        print(f"FAIL: num_bins must be a positive integer, got {nb}", file=sys.stderr)
        return 1

    if "bins" in out:
        bins = out["bins"]
        if not isinstance(bins, list) or len(bins) != nb:
            print(f"FAIL: bins must be a list of {nb} groups", file=sys.stderr)
            return 1
        seen: set[int] = set()
        for idx, grp in enumerate(bins):
            if not isinstance(grp, list) or not grp:
                print(f"FAIL: bin {idx} must be a non-empty list", file=sys.stderr)
                return 1
            tot = 0
            for j in grp:
                if not isinstance(j, int) or isinstance(j, bool) or j < 0 or j >= n:
                    print(f"FAIL: bin {idx} has invalid item id {j!r}", file=sys.stderr)
                    return 1
                if j in seen:
                    print(f"FAIL: item {j} is in more than one bin", file=sys.stderr)
                    return 1
                seen.add(j)
                tot += weights[j]
            if tot > capacity:
                print(f"FAIL: bin {idx} weight {tot} exceeds capacity {capacity}", file=sys.stderr)
                return 1
        if seen != set(range(n)):
            print("FAIL: bins do not cover every item exactly once", file=sys.stderr)
            return 1

    print(f"OK: num_bins={nb}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
