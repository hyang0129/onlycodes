#!/usr/bin/env python3
"""Workspace generator for ``data_engineering__filter_aggregate_transactions_hard``.

Writes four CSVs with substantially different schemas:

* ``tx_na.csv``    — USD, date YYYY-MM-DD, voided "true"/"false"
* ``tx_eu.csv``    — EUR (~25% with "€" prefix), date DD/MM/YYYY, cancelled "yes"/"no"
* ``tx_apac.csv``  — JPY integer amounts, date as epoch milliseconds, rejected "1"/"0"
* ``tx_latam.csv`` — BRL (~35% with "R$" prefix), datetime YYYY-MM-DD HH:MM:SS, blocked "Y"/"N"

All four share the same five sectors (finance, food, healthcare, retail, tech).
The agent must filter to only food/retail/tech, year 2026, non-voided, and
USD-equivalent >= 10.00, then aggregate by sector.

Realistic messiness:
* LATAM amounts have leading/trailing whitespace on ~20% of rows.
* ~15% of all transactions are voided/cancelled/rejected/blocked.
* ~30% of transactions fall outside 2026 (2025 or 2027) to test the year filter.
* ~10% of transactions convert to < 10.00 USD to test the amount threshold.
"""

from __future__ import annotations

import argparse
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SECTORS = ["finance", "food", "healthcare", "retail", "tech"]
_VOID_PROB = 0.15
_OUT_OF_YEAR_PROB = 0.30
_BELOW_THRESHOLD_PROB = 0.10

_N_NA = 200
_N_EU = 200
_N_APAC = 200
_N_LATAM = 200

_EUR_SIGN_PROB = 0.25
_BRL_SIGN_PROB = 0.35
_LATAM_WS_PROB = 0.20

# Date window for in-year (2026) rows
_Y2026_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
_Y2026_SECONDS = 365 * 24 * 3600  # 2026 is not a leap year

# Out-of-year choices: 2025 or 2027
_OUT_YEAR_STARTS = [
    datetime(2025, 1, 1, tzinfo=timezone.utc),
    datetime(2027, 1, 1, tzinfo=timezone.utc),
]
_OUT_YEAR_SECONDS = 365 * 24 * 3600


def _random_ts_2026(rng: random.Random) -> datetime:
    return _Y2026_START + timedelta(seconds=rng.randrange(_Y2026_SECONDS))


def _random_ts_out(rng: random.Random) -> datetime:
    base = rng.choice(_OUT_YEAR_STARTS)
    return base + timedelta(seconds=rng.randrange(_OUT_YEAR_SECONDS))


def _amount_above_threshold(rng: random.Random, rate: float) -> float:
    """Return a local-currency amount that converts to >= 10.00 USD."""
    usd_min = 10.0 / rate
    return round(rng.uniform(usd_min, usd_min * 50), 2)


def _amount_below_threshold(rng: random.Random, rate: float) -> float:
    """Return a local-currency amount that converts to < 10.00 USD."""
    usd_max = 9.99 / rate
    return round(rng.uniform(0.01, usd_max), 2)


def _write_na(rng: random.Random, output_dir: Path, n: int) -> None:
    rows = []
    for i in range(n):
        ts = _random_ts_out(rng) if rng.random() < _OUT_OF_YEAR_PROB else _random_ts_2026(rng)
        voided = rng.random() < _VOID_PROB
        if rng.random() < _BELOW_THRESHOLD_PROB:
            amt = _amount_below_threshold(rng, 1.0)
        else:
            amt = _amount_above_threshold(rng, 1.0)
        rows.append(
            {
                "tx_id": f"NA-{i:06d}",
                "merchant_id": f"merch-{rng.randint(1, 50):03d}",
                "sector": rng.choice(_SECTORS),
                "amount_usd": f"{amt:.2f}",
                "tx_date": ts.strftime("%Y-%m-%d"),
                "voided": "true" if voided else "false",
            }
        )
    rng.shuffle(rows)
    cols = ["tx_id", "merchant_id", "sector", "amount_usd", "tx_date", "voided"]
    with open(output_dir / "tx_na.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_eu(rng: random.Random, output_dir: Path, n: int) -> None:
    rows = []
    for i in range(n):
        ts = _random_ts_out(rng) if rng.random() < _OUT_OF_YEAR_PROB else _random_ts_2026(rng)
        cancelled = rng.random() < _VOID_PROB
        if rng.random() < _BELOW_THRESHOLD_PROB:
            amt = _amount_below_threshold(rng, 1.10)
        else:
            amt = _amount_above_threshold(rng, 1.10)
        amt_str = f"{amt:.2f}"
        if rng.random() < _EUR_SIGN_PROB:
            amt_str = f"€{amt_str}"  # € prefix
        rows.append(
            {
                "id": f"EU-{i:06d}",
                "vendor_id": f"merch-{rng.randint(1, 50):03d}",
                "category": rng.choice(_SECTORS),
                "amount_eur": amt_str,
                "date_eu": ts.strftime("%d/%m/%Y"),
                "cancelled": "yes" if cancelled else "no",
            }
        )
    rng.shuffle(rows)
    cols = ["id", "vendor_id", "category", "amount_eur", "date_eu", "cancelled"]
    with open(output_dir / "tx_eu.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_apac(rng: random.Random, output_dir: Path, n: int) -> None:
    rows = []
    for i in range(n):
        ts = _random_ts_out(rng) if rng.random() < _OUT_OF_YEAR_PROB else _random_ts_2026(rng)
        rejected = rng.random() < _VOID_PROB
        # JPY is integer; threshold is 10 * 150 = 1500 JPY
        if rng.random() < _BELOW_THRESHOLD_PROB:
            amt_jpy = rng.randint(1, 1499)
        else:
            amt_jpy = rng.randint(1500, 75000)
        epoch_ms = int(ts.timestamp() * 1000)
        rows.append(
            {
                "ref_no": f"APAC-{i:06d}",
                "merchant_code": f"merch-{rng.randint(1, 50):03d}",
                "type": rng.choice(_SECTORS),
                "amount_jpy": str(amt_jpy),
                "epoch_ms": str(epoch_ms),
                "rejected": "1" if rejected else "0",
            }
        )
    rng.shuffle(rows)
    cols = ["ref_no", "merchant_code", "type", "amount_jpy", "epoch_ms", "rejected"]
    with open(output_dir / "tx_apac.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_latam(rng: random.Random, output_dir: Path, n: int) -> None:
    rows = []
    for i in range(n):
        ts = _random_ts_out(rng) if rng.random() < _OUT_OF_YEAR_PROB else _random_ts_2026(rng)
        blocked = rng.random() < _VOID_PROB
        if rng.random() < _BELOW_THRESHOLD_PROB:
            amt = _amount_below_threshold(rng, 0.20)  # 1/5
        else:
            amt = _amount_above_threshold(rng, 0.20)
        amt_str = f"{amt:.2f}"
        if rng.random() < _BRL_SIGN_PROB:
            amt_str = f"R${amt_str}"
        if rng.random() < _LATAM_WS_PROB:
            left = " " * rng.randint(1, 2) if rng.random() < 0.6 else ""
            right = " " * rng.randint(1, 2) if rng.random() < 0.6 else ""
            if not left and not right:
                left = " "
            amt_str = f"{left}{amt_str}{right}"
            if not amt_str.startswith('"'):
                amt_str = f'"{amt_str}"'
        rows.append(
            {
                "reference": f"LATAM-{i:06d}",
                "merch_id": f"merch-{rng.randint(1, 50):03d}",
                "segment": rng.choice(_SECTORS),
                "amount_brl": amt_str,
                "datetime_str": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "blocked": "Y" if blocked else "N",
            }
        )
    rng.shuffle(rows)
    cols = ["reference", "merch_id", "segment", "amount_brl", "datetime_str", "blocked"]
    with open(output_dir / "tx_latam.csv", "w", newline="") as fh:
        fh.write(",".join(cols) + "\n")
        for r in rows:
            fh.write(
                f"{r['reference']},{r['merch_id']},{r['segment']},{r['amount_brl']},{r['datetime_str']},{r['blocked']}\n"
            )


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_na(rng, output_dir, _N_NA)
    _write_eu(rng, output_dir, _N_EU)
    _write_apac(rng, output_dir, _N_APAC)
    _write_latam(rng, output_dir, _N_LATAM)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--instance-id", type=str, required=False, default="")
    args = ap.parse_args()
    generate(args.output_dir, args.seed)


if __name__ == "__main__":
    main()
