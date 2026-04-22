#!/usr/bin/env python3
"""Workspace generator for data_processing__duplicate_orders.

Writes ``orders.jsonl`` into the output directory: ~5,000 synthetic order
rows, seeded, with a known rate of duplicate submissions within the 300s
window so the task is non-trivial but deterministic.

Stdlib-only (pandas/numpy are NOT available in the materialize env — see
SCHEMA §5.1 and the realism checklist).
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

_SKUS = [
    "SKU-APRN-001", "SKU-BOOK-045", "SKU-CANDLE-17", "SKU-DESK-003",
    "SKU-EARBUDS-22", "SKU-FLASK-09", "SKU-GAME-bd", "SKU-HAT-77",
    "SKU-INK-205", "SKU-JACKET-lg", "SKU-KETTLE-1l", "SKU-LAMP-walnut",
    "SKU-MAT-yoga", "SKU-NOTEBK-a5", "SKU-PEN-fine", "SKU-RUG-2x3",
    "SKU-SHOE-10w", "SKU-TOWEL-bath", "SKU-UMBRELLA-blk", "SKU-VASE-clay",
]

_STATUS_CHOICES = ("placed",) * 18 + ("cancelled",) * 1 + ("refunded",) * 1

_N_CUSTOMERS = 900
_N_ROWS = 5_000
_TS_BASE = 1_700_000_000.0
_TS_SPAN = 7 * 24 * 3600.0  # one week of orders

# Probability that a given row gets a near-duplicate follow-up within 300s.
_DUP_RATE = 0.06
# Probability that a "duplicate cluster" contains a 3rd twin (tests >2 pairs).
_TRIPLE_RATE = 0.15


def _rand_amount_cents(rng: random.Random) -> int:
    # Realistic-ish amounts: $5 to $250, coarse dollar steps mostly.
    dollars = rng.choice([rng.randint(5, 250), rng.randint(5, 50), 19, 29, 49, 99])
    cents = rng.choice([0, 0, 0, 99, 95, 50, 25])
    return dollars * 100 + cents


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    rows: list[dict] = []
    next_id = 1

    def new_id() -> str:
        nonlocal next_id
        rid = f"ord_{next_id:06d}"
        next_id += 1
        return rid

    # We generate "base" orders and then sometimes tack on dup twins/triples.
    # Each base consumes a variable number of output rows, so the total may
    # exceed _N_ROWS slightly; trim to _N_ROWS at the end.
    while len(rows) < _N_ROWS:
        customer = f"cust_{rng.randint(1, _N_CUSTOMERS):04d}"
        sku = rng.choice(_SKUS)
        amount = _rand_amount_cents(rng)
        ts = _TS_BASE + rng.uniform(0, _TS_SPAN)
        status = rng.choice(_STATUS_CHOICES)
        rows.append({
            "order_id": new_id(),
            "customer_id": customer,
            "sku": sku,
            "amount_cents": amount,
            "created_ts": round(ts, 4),
            "status": status,
        })

        if rng.random() < _DUP_RATE:
            # Within-window twin: same customer/sku/amount, different time.
            delta = rng.uniform(0.5, 290.0) * rng.choice([1, -1])
            rows.append({
                "order_id": new_id(),
                "customer_id": customer,
                "sku": sku,
                "amount_cents": amount,
                "created_ts": round(ts + delta, 4),
                "status": rng.choice(_STATUS_CHOICES),
            })
            if rng.random() < _TRIPLE_RATE:
                delta2 = rng.uniform(0.5, 290.0) * rng.choice([1, -1])
                # make sure all three are within 300s of each other: pick small delta2
                delta2 = rng.uniform(-150, 150)
                rows.append({
                    "order_id": new_id(),
                    "customer_id": customer,
                    "sku": sku,
                    "amount_cents": amount,
                    "created_ts": round(ts + delta2, 4),
                    "status": rng.choice(_STATUS_CHOICES),
                })

        # Occasional "near-miss": same cust+sku+amount but >300s apart — should
        # NOT appear in output. This keeps trivial group-by-only solutions
        # honest.
        if rng.random() < 0.03:
            delta = rng.uniform(400, 6 * 3600)  # 6.7 min to 6 hrs later
            rows.append({
                "order_id": new_id(),
                "customer_id": customer,
                "sku": sku,
                "amount_cents": amount,
                "created_ts": round(ts + delta, 4),
                "status": rng.choice(_STATUS_CHOICES),
            })

    # Shuffle so adjacency in file is not informative.
    rng.shuffle(rows)
    rows = rows[:_N_ROWS]

    out = output_dir / "orders.jsonl"
    with open(out, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


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
