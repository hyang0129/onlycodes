#!/usr/bin/env python3
"""Workspace generator for ``data_science__rolling_p95_aggregation_medium``.

Writes ``latency.csv`` with 168 rows and columns ``t, latency_ms`` in
sequential ``t`` order (0..167) — one week of hourly observations.

Construction (stdlib only, hermetic at materialize time):

  * Base latency: ``base = 80 + 10 * day_of_week_phase(t)`` — adds a
    weak weekly drift but stays in the ~70..90ms band.
  * Per-hour noise: log-normal-shaped via ``base + abs(N(0, 20))``,
    so the per-hour distribution is right-skewed and most values
    cluster in ~70..150ms.
  * Spike clusters: two blocks of consecutive "stress" hours where
    latency jumps to ~300ms ± 30ms. Blocks are positioned so the
    trailing 24-hour rolling P95 will cross the 200ms threshold for a
    well-defined run of t values:
      - block 1: t = 50..68  (19 hours of high latency)
      - block 2: t = 110..127 (18 hours of high latency)
  * The block spacing (~40 hours between block-1 end at t=68 and
    block-2 start at t=110) exceeds the 24-hour window, so each
    block's effect on the rolling P95 decays cleanly before the next
    block begins. With ~95% of inliers below ~140ms and spike values
    at ~270..330ms, the rolling P95 inside a spike's tail is either
    > 250 (sig) or < 180 (not sig) — wide separation from the 200ms
    threshold.
"""

from __future__ import annotations

import argparse
import math
import random
from pathlib import Path

_N_ROWS = 168  # one week, hourly
_BASE_INTERCEPT = 80.0
_BASE_AMPLITUDE = 10.0  # weekly drift
_INLIER_NOISE_STD = 20.0
_SPIKE_BLOCKS = ((50, 68), (110, 127))  # inclusive ranges
_SPIKE_MEAN = 300.0
_SPIKE_NOISE_STD = 30.0


def _is_spike_hour(t: int) -> bool:
    for lo, hi in _SPIKE_BLOCKS:
        if lo <= t <= hi:
            return True
    return False


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    rows: list[tuple[int, float]] = []
    for t in range(_N_ROWS):
        weekly = _BASE_AMPLITUDE * math.sin(2 * math.pi * t / 168.0)
        base = _BASE_INTERCEPT + weekly
        if _is_spike_hour(t):
            v = _SPIKE_MEAN + rng.gauss(0.0, _SPIKE_NOISE_STD)
        else:
            # Right-skewed inlier noise — abs() of a normal draw.
            v = base + abs(rng.gauss(0.0, _INLIER_NOISE_STD))
        rows.append((t, max(v, 0.0)))  # latency is non-negative

    out_path = output_dir / "latency.csv"
    with open(out_path, "w") as f:
        f.write("t,latency_ms\n")
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
