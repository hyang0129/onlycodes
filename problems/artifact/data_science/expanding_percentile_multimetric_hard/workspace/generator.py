#!/usr/bin/env python3
"""Workspace generator for ``data_science__expanding_percentile_multimetric_hard``.

Writes ``metrics.csv`` with 200 rows and columns
``t, metric_a, metric_b, metric_c`` in sequential ``t`` order.

Construction (stdlib only, hermetic at materialize time):

  * metric_a ~ N(50, 10)           — symmetric, well-spread
  * metric_b ~ Exponential(1.0) * 10 — right-skewed (large tail);
                                       p99 noticeably > p90 > p50
  * metric_c ~ Uniform(0, 100)     — flat distribution

  All three distributions have wide-enough spread that the expanding
  percentile values at each checkpoint round-trip to ±0.01 across any
  of the equivalent computation routes (numpy.quantile,
  numpy.percentile, pd.Series.expanding().quantile, pd.Series.quantile
  on the slice). The dataset is large enough (50+ samples at the
  earliest checkpoint t=49) that percentile estimates are well-defined
  and stable across rounding noise.
"""

from __future__ import annotations

import argparse
import math
import random
from pathlib import Path

_N_ROWS = 200


def _exp_draw(rng: random.Random, scale: float) -> float:
    # Inverse-CDF method for Exp(scale). rng.random() is open at 0 in CPython,
    # so log(1 - u) is always finite.
    u = rng.random()
    return -scale * math.log(1.0 - u)


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    rows: list[tuple[int, float, float, float]] = []
    for t in range(_N_ROWS):
        a = rng.gauss(50.0, 10.0)
        b = _exp_draw(rng, 1.0) * 10.0
        c = rng.uniform(0.0, 100.0)
        rows.append((t, a, b, c))

    out_path = output_dir / "metrics.csv"
    with open(out_path, "w") as f:
        f.write("t,metric_a,metric_b,metric_c\n")
        for t, a, b, c in rows:
            f.write(f"{t},{a:.12g},{b:.12g},{c:.12g}\n")


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
