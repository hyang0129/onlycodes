#!/usr/bin/env python3
"""Workspace generator for stateful_reasoning__event_ledger.

Writes ``transactions.jsonl`` into the output directory (1,000 rows over
ACC01..ACC30). ``initial_balances.json`` is hand-curated and stays checked
in.

The mix includes deposits, withdrawals, and transfers — with some
insufficient-funds cases so the grader's ``rejected`` list is non-empty.
See issue #118.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

_N_TXN = 1000
_N_ACCOUNTS = 30


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    accounts = [f"ACC{n:02d}" for n in range(1, _N_ACCOUNTS + 1)]
    path = output_dir / "transactions.jsonl"
    with open(path, "w") as f:
        for i in range(1, _N_TXN + 1):
            # 40% deposit, 35% withdrawal, 25% transfer
            r = rng.random()
            if r < 0.40:
                t_type = "deposit"
            elif r < 0.75:
                t_type = "withdrawal"
            else:
                t_type = "transfer"

            # Amounts: most are small/medium; ~10% are large so some
            # withdrawals/transfers are rejected for insufficient funds.
            if rng.random() < 0.10:
                amount = round(rng.uniform(400.0, 1500.0), 2)
            else:
                amount = round(rng.uniform(1.0, 300.0), 2)

            row: dict = {"txn_id": f"T{i:04d}", "type": t_type, "amount": amount}
            if t_type == "transfer":
                a, b = rng.sample(accounts, 2)
                row["from"] = a
                row["to"] = b
            else:
                row["account"] = rng.choice(accounts)

            f.write(json.dumps(row) + "\n")


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
