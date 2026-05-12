#!/usr/bin/env python3
"""Workspace generator for ``data_engineering__filter_aggregate_sales_easy``.

Writes two CSVs (``sales_region_a.csv``, ``sales_region_b.csv``) with the
same schema.  Both files share the product categories so the agent must
aggregate across both files into a single per-category summary.

Realistic messiness:
* ~15% of ``amount`` values have leading and/or trailing whitespace.
* Status is distributed ~60% completed, ~20% pending, ~12% refunded,
  ~8% cancelled so that the filter step is non-trivial.
"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

_CATEGORIES = ["clothing", "electronics", "food", "home", "sports"]
_STATUSES = ["completed", "pending", "refunded", "cancelled"]
_STATUS_WEIGHTS = [0.60, 0.20, 0.12, 0.08]

_N_A = 200
_N_B = 200
_AMOUNT_WS_PROB = 0.15


def _generate_rows(
    rng: random.Random, n: int, prefix: str
) -> list[dict]:
    rows = []
    for i in range(n):
        category = rng.choice(_CATEGORIES)
        status = rng.choices(_STATUSES, weights=_STATUS_WEIGHTS, k=1)[0]
        amount_val = round(rng.uniform(5.0, 999.99), 2)
        amount_str = f"{amount_val:.2f}"
        if rng.random() < _AMOUNT_WS_PROB:
            left = " " * rng.randint(1, 2) if rng.random() < 0.6 else ""
            right = " " * rng.randint(1, 2) if rng.random() < 0.6 else ""
            if not left and not right:
                left = " "
            amount_str = f"{left}{amount_val:.2f}{right}"
            amount_str = f'"{amount_str}"'
        rows.append(
            {
                "order_id": f"{prefix}-{i:06d}",
                "category": category,
                "amount": amount_str,
                "status": status,
            }
        )
    rng.shuffle(rows)
    return rows


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    cols = ["order_id", "category", "amount", "status"]

    for filename, prefix, n in [
        ("sales_region_a.csv", "A", _N_A),
        ("sales_region_b.csv", "B", _N_B),
    ]:
        rows = _generate_rows(rng, n, prefix)
        output_dir.mkdir(parents=True, exist_ok=True)
        with open(output_dir / filename, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
            w.writeheader()
            for r in rows:
                # amount may already be quoted; write raw to avoid double-quoting
                fh.write(
                    f"{r['order_id']},{r['category']},{r['amount']},{r['status']}\n"
                )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--instance-id", type=str, required=False, default="")
    args = ap.parse_args()
    generate(args.output_dir, args.seed)


if __name__ == "__main__":
    main()
