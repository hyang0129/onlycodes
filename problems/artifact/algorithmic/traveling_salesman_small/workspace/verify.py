#!/usr/bin/env python3
"""Structural verifier for algorithmic__traveling_salesman_small."""

import json
import math
import sys
from pathlib import Path

STOPS = Path(__file__).parent / "stops.json"
OUTPUT = Path(__file__).parent / "output" / "tour.json"


def main() -> int:
    if not STOPS.is_file():
        print(f"FAIL: stops.json not found at {STOPS}", file=sys.stderr)
        return 1
    data = json.loads(STOPS.read_text())
    n = len(data["points"])
    depot = data["depot"]

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

    for key in ("tour_length", "tour"):
        if key not in out:
            print(f"FAIL: missing required key {key!r}", file=sys.stderr)
            return 1

    tour = out["tour"]
    tl = out["tour_length"]

    if not isinstance(tour, list) or len(tour) != n + 1:
        print(f"FAIL: tour must be a list of length {n+1}", file=sys.stderr)
        return 1
    if tour[0] != depot or tour[-1] != depot:
        print(f"FAIL: tour must start and end at depot ({depot})", file=sys.stderr)
        return 1
    middle = tour[1:-1]
    if sorted(middle) != [i for i in range(n) if i != depot]:
        print("FAIL: tour is not a valid Hamiltonian permutation of non-depot points", file=sys.stderr)
        return 1

    if isinstance(tl, bool) or not isinstance(tl, (int, float)):
        print(f"FAIL: tour_length must be a number", file=sys.stderr)
        return 1
    if tl <= 0:
        print(f"FAIL: tour_length must be positive, got {tl}", file=sys.stderr)
        return 1

    # Sanity: declared length matches tour
    pts = data["points"]
    computed = 0.0
    for a, b in zip(tour[:-1], tour[1:]):
        ax, ay = pts[a]
        bx, by = pts[b]
        computed += math.hypot(ax - bx, ay - by)
    if abs(computed - tl) > 1e-6 * max(1.0, abs(computed)):
        print(f"FAIL: tour_length {tl} does not match computed {computed}", file=sys.stderr)
        return 1

    print(f"OK: tour_length={tl:.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
