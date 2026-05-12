#!/usr/bin/env python3
"""Workspace generator for ``data_engineering__filter_aggregate_support_tickets_medium``.

Writes three CSVs with deliberately inconsistent schemas:

* ``tickets_west.csv``    — ``resolved`` column is ``"1"``/``"0"``.
* ``tickets_east.csv``    — ``is_resolved`` column is ``"true"``/``"false"``.
* ``tickets_central.csv`` — ``dept`` instead of ``category``; ``status``
                             column is ``"closed"``/``"open"``;
                             ~30 % of ``cost_usd`` values carry a ``$`` prefix.

Realistic messiness:
* ~20 % of ``cost_usd`` values in all files have leading/trailing whitespace.
* Priority distribution: ~20% critical, ~30% high, ~30% medium, ~20% low.
* Resolved rate: ~55% so the filter step removes a meaningful fraction.
"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

_CATEGORIES = ["billing", "hardware", "network", "security", "software"]
_PRIORITIES = ["critical", "high", "medium", "low"]
_PRIORITY_WEIGHTS = [0.20, 0.30, 0.30, 0.20]

_N_WEST = 200
_N_EAST = 200
_N_CENTRAL = 200

_RESOLVED_PROB = 0.55
_COST_WS_PROB = 0.20
_CENTRAL_DOLLAR_PROB = 0.30


def _cost_str(rng: random.Random, ws_prob: float, dollar_prob: float = 0.0) -> str:
    val = round(rng.uniform(20.0, 499.99), 2)
    s = f"{val:.2f}"
    if rng.random() < dollar_prob:
        s = f"${s}"
    if rng.random() < ws_prob:
        left = " " * rng.randint(1, 2) if rng.random() < 0.6 else ""
        right = " " * rng.randint(1, 2) if rng.random() < 0.6 else ""
        if not left and not right:
            left = " "
        s = f"{left}{s}{right}"
        if not s.startswith('"'):
            s = f'"{s}"'
    return s


def _write_west(rng: random.Random, output_dir: Path) -> None:
    cols = ["ticket_id", "category", "priority", "resolved", "cost_usd"]
    rows = []
    for i in range(_N_WEST):
        rows.append(
            {
                "ticket_id": f"W-{i:06d}",
                "category": rng.choice(_CATEGORIES),
                "priority": rng.choices(_PRIORITIES, weights=_PRIORITY_WEIGHTS, k=1)[0],
                "resolved": "1" if rng.random() < _RESOLVED_PROB else "0",
                "cost_usd": _cost_str(rng, _COST_WS_PROB),
            }
        )
    rng.shuffle(rows)
    with open(output_dir / "tickets_west.csv", "w", newline="") as fh:
        fh.write(",".join(cols) + "\n")
        for r in rows:
            fh.write(f"{r['ticket_id']},{r['category']},{r['priority']},{r['resolved']},{r['cost_usd']}\n")


def _write_east(rng: random.Random, output_dir: Path) -> None:
    cols = ["ticket_id", "category", "priority", "is_resolved", "cost_usd"]
    rows = []
    for i in range(_N_EAST):
        rows.append(
            {
                "ticket_id": f"E-{i:06d}",
                "category": rng.choice(_CATEGORIES),
                "priority": rng.choices(_PRIORITIES, weights=_PRIORITY_WEIGHTS, k=1)[0],
                "is_resolved": "true" if rng.random() < _RESOLVED_PROB else "false",
                "cost_usd": _cost_str(rng, _COST_WS_PROB),
            }
        )
    rng.shuffle(rows)
    with open(output_dir / "tickets_east.csv", "w", newline="") as fh:
        fh.write(",".join(cols) + "\n")
        for r in rows:
            fh.write(f"{r['ticket_id']},{r['category']},{r['priority']},{r['is_resolved']},{r['cost_usd']}\n")


def _write_central(rng: random.Random, output_dir: Path) -> None:
    cols = ["ticket_id", "dept", "priority", "status", "cost_usd"]
    rows = []
    for i in range(_N_CENTRAL):
        rows.append(
            {
                "ticket_id": f"C-{i:06d}",
                "dept": rng.choice(_CATEGORIES),
                "priority": rng.choices(_PRIORITIES, weights=_PRIORITY_WEIGHTS, k=1)[0],
                "status": "closed" if rng.random() < _RESOLVED_PROB else "open",
                "cost_usd": _cost_str(rng, _COST_WS_PROB, _CENTRAL_DOLLAR_PROB),
            }
        )
    rng.shuffle(rows)
    with open(output_dir / "tickets_central.csv", "w", newline="") as fh:
        fh.write(",".join(cols) + "\n")
        for r in rows:
            fh.write(
                f"{r['ticket_id']},{r['dept']},{r['priority']},{r['status']},{r['cost_usd']}\n"
            )


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_west(rng, output_dir)
    _write_east(rng, output_dir)
    _write_central(rng, output_dir)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--instance-id", type=str, required=False, default="")
    args = ap.parse_args()
    generate(args.output_dir, args.seed)


if __name__ == "__main__":
    main()
