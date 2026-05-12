#!/usr/bin/env python3
"""Workspace generator for ``data_engineering__customer_orders_join_easy``.

Writes two CSVs with deliberately inconsistent schemas:

  * ``orders_north.csv`` — columns ``customer_id,order_id,order_date,amount``.
    ``order_date`` is ISO ``YYYY-MM-DD``. ``amount`` is a plain number; a
    subset of rows have leading/trailing whitespace around the value.

  * ``orders_south.csv`` — columns ``cust_id,order_id,date,amount_str``.
    ``date`` is US ``MM/DD/YYYY``. ``amount_str`` is mostly ``$49.99`` but
    a subset of rows omit the ``$`` prefix.

No missing values, no duplicate keys. Order IDs are namespaced (``N-…``
versus ``S-…``) so the merged set has no key collisions.
"""

from __future__ import annotations

import argparse
import random
from datetime import date, timedelta
from pathlib import Path

_N_NORTH = 150
_N_SOUTH = 150
_N_CUSTOMERS = 50

_DATE_START = date(2026, 1, 1)
_DATE_DAYS = 90  # Jan 1 .. Mar 31 2026 inclusive

# Probability that a north row has whitespace around the amount.
_NORTH_AMOUNT_WS_PROB = 0.15
# Probability that a south row omits the ``$`` prefix on amount.
_SOUTH_AMOUNT_NO_DOLLAR_PROB = 0.20


def _random_date(rng: random.Random) -> date:
    return _DATE_START + timedelta(days=rng.randrange(_DATE_DAYS))


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)

    customers = [f"C{n:03d}" for n in range(1, _N_CUSTOMERS + 1)]

    # ---- orders_north.csv ----------------------------------------------------
    north_path = output_dir / "orders_north.csv"
    with open(north_path, "w") as f:
        f.write("customer_id,order_id,order_date,amount\n")
        for i in range(1, _N_NORTH + 1):
            cust = rng.choice(customers)
            oid = f"N-{i:05d}"
            d = _random_date(rng)
            amt = round(rng.uniform(5.0, 500.0), 2)
            amt_str = f"{amt:.2f}"
            if rng.random() < _NORTH_AMOUNT_WS_PROB:
                # Add leading and/or trailing whitespace.
                left = " " * rng.randint(1, 2) if rng.random() < 0.5 else ""
                right = " " * rng.randint(1, 2) if rng.random() < 0.5 else ""
                # Ensure at least one side has whitespace.
                if not left and not right:
                    left = " "
                amt_str = f"{left}{amt}{right}"
                # quote because of internal whitespace
                amt_str = f'"{amt_str}"'
            f.write(f"{cust},{oid},{d.isoformat()},{amt_str}\n")

    # ---- orders_south.csv ----------------------------------------------------
    south_path = output_dir / "orders_south.csv"
    with open(south_path, "w") as f:
        f.write("cust_id,order_id,date,amount_str\n")
        for i in range(1, _N_SOUTH + 1):
            cust = rng.choice(customers)
            oid = f"S-{i:05d}"
            d = _random_date(rng)
            amt = round(rng.uniform(5.0, 500.0), 2)
            us_date = f"{d.month:02d}/{d.day:02d}/{d.year:04d}"
            if rng.random() < _SOUTH_AMOUNT_NO_DOLLAR_PROB:
                amt_str = f"{amt:.2f}"
            else:
                amt_str = f"${amt:.2f}"
            f.write(f"{cust},{oid},{us_date},{amt_str}\n")


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
