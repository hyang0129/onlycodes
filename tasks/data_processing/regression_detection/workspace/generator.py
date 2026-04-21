#!/usr/bin/env python3
"""Workspace generator for data_processing__regression_detection.

Writes 48 ``metrics_<date>_<hour>.jsonl`` files (24 hours for 2024-01-14 and
24 hours for 2024-01-15) into the output directory. Some endpoints have a
clear day-over-day p95 regression; the top-3 are stable under the seeded RNG.

See issue #118.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

# endpoint -> (baseline_ms_day1, baseline_ms_day2)
# endpoints with a day-2 > day-1 baseline will show a regression; the
# magnitude is proportional to the delta.
_ENDPOINTS = {
    "/api/users":              (40.0,  50.0),
    "/api/orders":             (60.0,  75.0),
    "/api/search":             (120.0, 360.0),     # big regressor
    "/api/payments":           (80.0,  300.0),     # big regressor
    "/api/inventory":          (50.0,  55.0),
    "/api/notifications":      (25.0,  30.0),
    "/api/reports/generate":   (200.0, 800.0),     # biggest regressor
    "/api/catalog":            (90.0,  100.0),
    "/api/cart":               (35.0,  40.0),
    "/api/checkout":           (100.0, 140.0),
    "/api/profile":            (45.0,  48.0),
    "/api/recommendations":    (150.0, 170.0),
}

_ROWS_PER_HOUR = 50


def _sample_latency(rng: random.Random, base: float) -> float:
    """A positive latency that has a long right-tail at p95."""
    # Mix: 85% near baseline (gaussian), 15% heavy tail up to ~4x baseline.
    if rng.random() < 0.15:
        return max(1.0, rng.uniform(base, base * 4.0))
    return max(1.0, rng.gauss(base, base * 0.25))


def _write_hour_file(
    out: Path,
    day: str,
    hour: int,
    rng: random.Random,
    day_index: int,  # 0 for yesterday, 1 for today
) -> None:
    path = out / f"metrics_{day}_{hour:02d}.jsonl"
    with open(path, "w") as f:
        eps = list(_ENDPOINTS.keys())
        for _ in range(_ROWS_PER_HOUR):
            ep = rng.choice(eps)
            base = _ENDPOINTS[ep][day_index]
            latency = _sample_latency(rng, base)
            f.write(json.dumps({
                "endpoint": ep,
                "latency_ms": round(latency, 3),
            }) + "\n")


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    for day, day_index in (("2024-01-14", 0), ("2024-01-15", 1)):
        for hour in range(24):
            _write_hour_file(output_dir, day, hour, rng, day_index)


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
