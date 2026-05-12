#!/usr/bin/env python3
"""Workspace generator for ``data_engineering__orders_lookup_join_medium``.

Writes three CSVs:

  * ``customers.csv`` — 100 rows. ``customer_id`` is ``C00001``..``C00100``.
    ~10% of rows have an empty ``email`` field.
  * ``products.csv`` — 30 rows. ``sku`` is ``P1``..``P30`` (no padding,
    no dash).
  * ``orders.csv`` — 200 rows. ``cust_id`` is a plain integer; ``prod_code``
    is dash-and-zero-padded (``P-007``, ``P-023``). ~18% of orders point at
    non-existent customer or product ids (orphans) which the agent must
    drop.

No file exceeds a few KB. All IDs are deterministic under the seeded RNG.
"""

from __future__ import annotations

import argparse
import csv
import random
from datetime import date, timedelta
from pathlib import Path

_N_CUSTOMERS = 100
_N_PRODUCTS = 30
_N_ORDERS = 200
_CUSTOMER_EMPTY_EMAIL_PROB = 0.10
_ORPHAN_PROB = 0.18

_FIRST_NAMES = [
    "Alex", "Brian", "Cara", "Dani", "Eve", "Felix", "Greta", "Hugo",
    "Ines", "Jane", "Kai", "Lia", "Mia", "Noor", "Owen", "Pia",
    "Quin", "Ravi", "Sara", "Theo", "Uma", "Vik", "Wren", "Xian",
    "Yara", "Zane",
]
_LAST_NAMES = [
    "Allen", "Brown", "Chen", "Davis", "Edwards", "Fischer", "Garcia",
    "Hall", "Iyer", "Jones", "Kim", "Lopez", "Murphy", "Nguyen",
    "Owens", "Patel", "Quinn", "Roy", "Smith", "Tan", "Ueda", "Vance",
    "Wong", "Xu", "Young", "Zhao",
]
_CATEGORIES = ["electronics", "apparel", "home", "grocery", "other"]
_PRODUCT_NOUNS = [
    "Lamp", "Shirt", "Mug", "Bread", "Cable", "Pants", "Pan", "Apple",
    "Headphones", "Jacket", "Bowl", "Chips", "Mouse", "Hat", "Knife",
    "Cheese", "Speaker", "Socks", "Plate", "Yogurt", "Webcam", "Belt",
    "Spoon", "Coffee", "Tablet", "Scarf", "Cup", "Eggs", "Charger",
    "Sweater",
]

_DATE_START = date(2026, 1, 1)
_DATE_DAYS = 60  # Jan 1 .. Feb 28-ish 2026


def _make_customers(rng: random.Random) -> list[dict]:
    rows = []
    for n in range(1, _N_CUSTOMERS + 1):
        first = rng.choice(_FIRST_NAMES)
        last = rng.choice(_LAST_NAMES)
        full = f"{first} {last}"
        if rng.random() < _CUSTOMER_EMPTY_EMAIL_PROB:
            email = ""
        else:
            email = f"{first.lower()}.{last.lower()}@example.com"
        rows.append({"customer_id": f"C{n:05d}", "name": full, "email": email})
    return rows


def _make_products(rng: random.Random) -> list[dict]:
    rows = []
    for n in range(1, _N_PRODUCTS + 1):
        noun = _PRODUCT_NOUNS[(n - 1) % len(_PRODUCT_NOUNS)]
        # Cycle through categories deterministically for spread.
        category = _CATEGORIES[(n - 1) % len(_CATEGORIES)]
        rows.append(
            {
                "sku": f"P{n}",
                "product_name": f"{noun} {n}",
                "category": category,
            }
        )
    return rows


def _make_orders(rng: random.Random) -> list[dict]:
    rows = []
    for n in range(1, _N_ORDERS + 1):
        oid = f"O-{n:05d}"
        d = _DATE_START + timedelta(days=rng.randrange(_DATE_DAYS))
        qty = rng.randint(1, 10)
        price = round(rng.uniform(5.0, 250.0), 2)
        # Decide orphan-ness independently for customer and product, but
        # only one needs to be invalid for the row to be orphan.
        if rng.random() < _ORPHAN_PROB:
            # Make customer or product reference invalid.
            if rng.random() < 0.5:
                # Invalid customer id (out of range).
                cust_n = rng.randint(_N_CUSTOMERS + 1, _N_CUSTOMERS + 100)
                prod_n = rng.randint(1, _N_PRODUCTS)
            else:
                cust_n = rng.randint(1, _N_CUSTOMERS)
                prod_n = rng.randint(_N_PRODUCTS + 1, _N_PRODUCTS + 50)
        else:
            cust_n = rng.randint(1, _N_CUSTOMERS)
            prod_n = rng.randint(1, _N_PRODUCTS)
        rows.append(
            {
                "order_id": oid,
                "cust_id": str(cust_n),
                "prod_code": f"P-{prod_n:03d}",
                "order_date": d.isoformat(),
                "quantity": str(qty),
                "unit_price": f"{price:.2f}",
            }
        )
    return rows


def _write_csv(path: Path, rows: list[dict], cols: list[str]) -> None:
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    _write_csv(
        output_dir / "customers.csv",
        _make_customers(rng),
        ["customer_id", "name", "email"],
    )
    _write_csv(
        output_dir / "products.csv",
        _make_products(rng),
        ["sku", "product_name", "category"],
    )
    _write_csv(
        output_dir / "orders.csv",
        _make_orders(rng),
        ["order_id", "cust_id", "prod_code", "order_date", "quantity", "unit_price"],
    )


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
