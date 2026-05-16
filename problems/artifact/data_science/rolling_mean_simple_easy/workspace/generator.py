#!/usr/bin/env python3
"""Workspace generator for ``data_science__rolling_mean_simple_easy``.

Writes ``daily.csv`` with 90 rows and columns ``t, value`` in
sequential ``t`` order (0..89).

Construction (stdlib only, hermetic at materialize time):

  * Smooth slow-drift component: ``trend(t) = 10 + 0.1 * t``.
  * Day-to-day noise: ``noise ~ N(0, 1.5)``.
  * Value: ``value(t) = trend(t) + noise(t)``.

  No structural assumptions are leveraged by the grader; the
  generator just needs to produce a sequence whose 7-day rolling mean
  reads as a well-defined arithmetic mean.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

_N_ROWS = 90
_TREND_INTERCEPT = 10.0
_TREND_SLOPE = 0.1
_NOISE_STD = 1.5


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    rows: list[tuple[int, float]] = []
    for t in range(_N_ROWS):
        trend = _TREND_INTERCEPT + _TREND_SLOPE * t
        noise = rng.gauss(0.0, _NOISE_STD)
        rows.append((t, trend + noise))

    out_path = output_dir / "daily.csv"
    with open(out_path, "w") as f:
        f.write("t,value\n")
        for t, v in rows:
            f.write(f"{t},{v:.12g}\n")


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
