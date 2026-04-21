#!/usr/bin/env python3
"""Workspace generator for data_processing__multi_file_cohort.

Writes 20 ``sales_region_NN.csv`` files into the output directory with
columns ``product_id,quantity,unit_price``. Total revenue per product is
stable under the seeded RNG, so the top-5 set is deterministic.

See issue #118.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

_N_REGIONS = 20
_N_PRODUCTS = 30
_ROWS_PER_REGION_MIN = 150
_ROWS_PER_REGION_MAX = 200


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)

    # Per-product baseline unit price and popularity weight. A handful of
    # products are deliberately high-value / high-volume so the top-5 is
    # clearly separated from the tail.
    product_ids = [f"P{n:03d}" for n in range(1, _N_PRODUCTS + 1)]
    weights = [rng.uniform(0.2, 2.0) for _ in range(_N_PRODUCTS)]
    # Elevate five products so the top-5 is unambiguous.
    for top in rng.sample(range(_N_PRODUCTS), 5):
        weights[top] *= 3.5
    base_prices = [round(rng.uniform(5.0, 500.0), 2) for _ in range(_N_PRODUCTS)]

    for r in range(1, _N_REGIONS + 1):
        path = output_dir / f"sales_region_{r:02d}.csv"
        n_rows = rng.randint(_ROWS_PER_REGION_MIN, _ROWS_PER_REGION_MAX)
        with open(path, "w") as f:
            f.write("product_id,quantity,unit_price\n")
            for _ in range(n_rows):
                idx = rng.choices(range(_N_PRODUCTS), weights=weights, k=1)[0]
                pid = product_ids[idx]
                qty = rng.randint(1, 10)
                # Small per-region price jitter around the product's base.
                price = round(base_prices[idx] * rng.uniform(0.9, 1.1), 2)
                f.write(f"{pid},{qty},{price}\n")


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
