#!/usr/bin/env python3
"""Workspace generator for data_processing__outlier_days. Stdlib-only."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import random
from pathlib import Path

_REGIONS = ["NORAM-east", "NORAM-west", "EMEA-north", "APAC-se"]
_PRODUCTS = [
    "SKU-001", "SKU-002", "SKU-003", "SKU-004", "SKU-005",
    "SKU-006", "SKU-007", "SKU-008", "SKU-009", "SKU-010",
    "SKU-011", "SKU-012", "SKU-013", "SKU-014", "SKU-015",
    "SKU-016", "SKU-017", "SKU-018", "SKU-019", "SKU-020",
]

_SPAN_DAYS = 120
_END_DATE = dt.date(2024, 3, 31)


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    rows: list[tuple[str, str, str, int]] = []

    start_date = _END_DATE - dt.timedelta(days=_SPAN_DAYS - 1)

    for region in _REGIONS:
        for product in _PRODUCTS:
            # Each series has its own baseline + noise profile.
            baseline = rng.randint(20, 400)
            noise = rng.uniform(2.0, 0.12 * baseline + 2.0)
            series_span = _SPAN_DAYS  # all series span the full window for simplicity

            values: list[int] = []
            for day_idx in range(series_span):
                # Weekly seasonality (weekend dip for most products).
                d = start_date + dt.timedelta(days=day_idx)
                seasonal = 0.8 if d.weekday() >= 5 else 1.0
                val = rng.gauss(baseline * seasonal, noise)
                values.append(max(0, int(round(val))))

            # Inject ~2-4 anomalies per series at known positions beyond day 14
            # so they have full windows.
            n_anom = rng.randint(2, 4)
            candidate_days = list(range(14, series_span))
            rng.shuffle(candidate_days)
            for pos in candidate_days[:n_anom]:
                direction = rng.choice([+1, -1])
                # Make anomaly large enough that |z| easily > 3.5.
                magnitude = max(noise * 6.0, baseline * 0.5)
                values[pos] = max(0, int(round(values[pos] + direction * magnitude)))

            for day_idx in range(series_span):
                d = start_date + dt.timedelta(days=day_idx)
                rows.append((region, product, d.isoformat(), values[day_idx]))

    rng.shuffle(rows)

    out = output_dir / "sales.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["region", "product", "date", "units_sold"])
        for row in rows:
            w.writerow(row)


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
