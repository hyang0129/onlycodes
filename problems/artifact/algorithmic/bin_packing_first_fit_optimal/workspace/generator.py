#!/usr/bin/env python3
"""Workspace generator for algorithmic__bin_packing_first_fit_optimal. Stdlib-only.

Writes ``parcels.json``: {capacity, weights} with 15 weights in [1, capacity].
Distribution is tuned so the optimal bin count is non-trivial (rarely 1 bin,
rarely 15 bins) and so first-fit-decreasing is NOT always optimal.
"""

from __future__ import annotations
import argparse, json, random
from pathlib import Path

_N_ITEMS = 15


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    capacity = rng.randint(80, 120)
    # Bias weights toward the 30%..80% capacity range so several items must
    # share a bin but greedy heuristics can mispack.
    weights = []
    for _ in range(_N_ITEMS):
        # Mixture: 60% medium weights, 40% small.
        if rng.random() < 0.6:
            w = rng.randint(int(0.30 * capacity), int(0.80 * capacity))
        else:
            w = rng.randint(int(0.05 * capacity), int(0.30 * capacity))
        w = max(1, min(capacity, w))
        weights.append(w)
    out = {"capacity": capacity, "weights": weights}
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
