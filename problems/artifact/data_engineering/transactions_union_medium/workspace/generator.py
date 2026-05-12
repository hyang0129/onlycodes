#!/usr/bin/env python3
"""Workspace generator for ``data_engineering__transactions_union_medium``.

Writes three quarterly transaction CSVs with deliberately divergent
schemas:

  * ``tx_q1.csv`` — narrow format. ``amount`` always populated;
    ``currency`` 3-letter code with **mixed case** (USD/usd/Usd).

  * ``tx_q2.csv`` — wide format: ``amount_usd``, ``amount_eur``,
    ``amount_gbp``. Per row, exactly one is populated, or — for a small
    minority — all three are empty (drop those).

  * ``tx_q3.csv`` — string-valued ``value`` column with multiple null
    encodings (``""``, ``"NULL"``, ``"N/A"``, ``"—"``). ``ccy`` field
    mixes 3-letter codes with full names (``Euro``, ``British Pound``).
    ``notes`` is free-form text **containing commas**, so the file uses
    CSV quoting.
"""

from __future__ import annotations

import argparse
import csv
import random
from datetime import date, timedelta
from pathlib import Path

_N_Q1 = 80
_N_Q2 = 80
_N_Q3 = 80

_DATE_START = date(2026, 1, 1)
_DATE_DAYS = 90

_Q1_CCY_FORMS = {
    "USD": ["USD", "usd", "Usd"],
    "EUR": ["EUR", "eur", "Eur"],
    "GBP": ["GBP", "gbp", "Gbp"],
}

_Q3_CCY_FORMS = {
    "USD": ["USD", "usd", "US Dollar", "us dollar"],
    "EUR": ["EUR", "Euro", "euro"],
    "GBP": ["GBP", "British Pound", "Pound Sterling"],
    # ``BAD`` — unrecognised currency; row gets dropped.
    "_DROP_BAD": ["JPY", "Yen", "CHF"],
}

_Q3_NULL_FORMS = ["", "NULL", "N/A", "—"]

_NOTE_FRAGMENTS = [
    "client follow-up",
    "ref invoice #123, paid in full",
    "manual adjustment, see ticket",
    "wire transfer",
    "refund, awaiting confirmation",
    "duplicate of earlier transaction",
]


def _random_date(rng: random.Random) -> date:
    return _DATE_START + timedelta(days=rng.randrange(_DATE_DAYS))


def _make_q1(rng: random.Random) -> None:
    rows = []
    for n in range(1, _N_Q1 + 1):
        canonical = rng.choice(list(_Q1_CCY_FORMS.keys()))
        ccy_form = rng.choice(_Q1_CCY_FORMS[canonical])
        amount = round(rng.uniform(10.0, 5000.0), 2)
        rows.append(
            {
                "tx_id": f"T1-{n:04d}",
                "tx_date": _random_date(rng).isoformat(),
                "amount": f"{amount:.2f}",
                "currency": ccy_form,
            }
        )
    return rows


def _make_q2(rng: random.Random) -> None:
    rows = []
    for n in range(1, _N_Q2 + 1):
        row = {
            "tx_id": f"T2-{n:04d}",
            "tx_date": _random_date(rng).isoformat(),
            "amount_usd": "",
            "amount_eur": "",
            "amount_gbp": "",
        }
        # ~8% of rows have all amounts empty → must be dropped.
        if rng.random() < 0.08:
            pass
        else:
            col = rng.choice(["amount_usd", "amount_eur", "amount_gbp"])
            row[col] = f"{round(rng.uniform(10.0, 5000.0), 2):.2f}"
        rows.append(row)
    return rows


def _make_q3(rng: random.Random) -> None:
    rows = []
    for n in range(1, _N_Q3 + 1):
        # Currency: 10% bad/unknown, 5% empty, else valid.
        roll_ccy = rng.random()
        if roll_ccy < 0.10:
            ccy_form = rng.choice(_Q3_CCY_FORMS["_DROP_BAD"])
        elif roll_ccy < 0.15:
            ccy_form = ""
        else:
            canonical = rng.choice(["USD", "EUR", "GBP"])
            ccy_form = rng.choice(_Q3_CCY_FORMS[canonical])

        # Value: 15% null-encoded, else valid number.
        if rng.random() < 0.15:
            value = rng.choice(_Q3_NULL_FORMS)
        else:
            value = f"{round(rng.uniform(10.0, 5000.0), 2):.2f}"

        # Notes: 60% have a comma-bearing note, 40% empty.
        if rng.random() < 0.60:
            notes = rng.choice(_NOTE_FRAGMENTS)
        else:
            notes = ""

        rows.append(
            {
                "tx_id": f"T3-{n:04d}",
                "tx_date": _random_date(rng).isoformat(),
                "value": value,
                "ccy": ccy_form,
                "notes": notes,
            }
        )
    return rows


def _write(path: Path, rows: list[dict], cols: list[str]) -> None:
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    _write(output_dir / "tx_q1.csv", _make_q1(rng), ["tx_id", "tx_date", "amount", "currency"])
    _write(
        output_dir / "tx_q2.csv",
        _make_q2(rng),
        ["tx_id", "tx_date", "amount_usd", "amount_eur", "amount_gbp"],
    )
    _write(
        output_dir / "tx_q3.csv",
        _make_q3(rng),
        ["tx_id", "tx_date", "value", "ccy", "notes"],
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
