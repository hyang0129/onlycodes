#!/usr/bin/env python3
"""Workspace generator for stateful_reasoning__inventory_reconciliation.

Writes transactions.jsonl with receive/ship/transfer/adjust events across
a small set of warehouses and SKUs. Mix is tuned so some ships and
transfers get rejected for insufficient stock. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

_N_TXN = 800
_WAREHOUSES = ["WH1", "WH2", "WH3", "WH4"]
_SKUS = [f"SKU-{c}" for c in "ABCDEFGH"]


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    path = output_dir / "transactions.jsonl"
    with open(path, "w") as f:
        for i in range(1, _N_TXN + 1):
            tid = f"T{i:05d}"
            r = rng.random()
            sku = rng.choice(_SKUS)
            if r < 0.40:
                wh = rng.choice(_WAREHOUSES)
                qty = rng.randint(1, 50)
                rec = {"id": tid, "type": "receive", "warehouse": wh, "sku": sku, "qty": qty}
            elif r < 0.70:
                wh = rng.choice(_WAREHOUSES)
                # occasionally large to force rejections
                qty = rng.randint(1, 60) if rng.random() < 0.8 else rng.randint(60, 200)
                rec = {"id": tid, "type": "ship", "warehouse": wh, "sku": sku, "qty": qty}
            elif r < 0.90:
                src = rng.choice(_WAREHOUSES)
                dst = rng.choice([w for w in _WAREHOUSES if w != src])
                qty = rng.randint(1, 40) if rng.random() < 0.8 else rng.randint(40, 150)
                rec = {"id": tid, "type": "transfer", "from": src, "to": dst,
                       "sku": sku, "qty": qty}
            else:
                wh = rng.choice(_WAREHOUSES)
                delta = rng.randint(-30, 30)
                if delta == 0:
                    delta = 1
                rec = {"id": tid, "type": "adjust", "warehouse": wh, "sku": sku,
                       "delta": delta}
            f.write(json.dumps(rec) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--instance-id", type=str, required=False, default="")
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    generate(args.output_dir, args.seed)


if __name__ == "__main__":
    main()
