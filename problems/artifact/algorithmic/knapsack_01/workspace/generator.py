#!/usr/bin/env python3
"""Workspace generator for algorithmic__knapsack_01. Stdlib-only.

Writes ``parcels.json``: capacity in [120, 200] and 30 items each with weight
and value. Value-to-weight ratios are deliberately non-monotone so greedy-by-
density is not always optimal.
"""

from __future__ import annotations
import argparse, json, random
from pathlib import Path

_N = 30


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    capacity = rng.randint(120, 200)
    items = []
    for i in range(_N):
        weight = rng.randint(8, 60)
        # Value is noisy multiple of weight; tail items have high value relative
        # to weight, so naive greedy can be fooled.
        base = weight * rng.uniform(0.8, 2.4)
        value = max(10, int(base + rng.randint(-15, 30)))
        items.append({"id": i, "weight": weight, "value": value})
    out = {"capacity": capacity, "items": items}
    (output_dir / "parcels.json").write_text(json.dumps(out, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--instance-id", type=str, required=False, default="")
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    generate(args.output_dir, args.seed)


if __name__ == "__main__":
    main()
