#!/usr/bin/env python3
"""Workspace generator for ``data_science__consecutive_change_anomaly_hard``.

Writes ``series.csv`` with 300 rows and columns ``t, value`` in
sequential ``t`` order (0..299). ``value`` is strictly positive
throughout so ``pct_change`` is well-defined.

Construction (stdlib only, hermetic at materialize time):

  * Calm baseline: ``value`` walks via multiplicative noise. Each
    "calm" step applies ``value *= (1 + small_delta)`` where
    ``small_delta`` is uniform in ``[-0.004, 0.004]`` — so every calm
    period has ``|pct_change| < 0.005``, comfortably below the 0.02
    threshold. Starting value is 100.0.
  * Spike runs: 6 spike-runs of exactly 4 consecutive large-magnitude
    periods each, placed at fixed offsets in t (rows 20..23, 60..63,
    100..103, 150..153, 200..203, 250..253). Within a spike run, each
    step uses ``small_delta`` uniform in either ``[+0.035, +0.055]``
    or ``[-0.055, -0.035]`` (sign chosen per-period, independently of
    surrounding periods). Every spike period has ``|pct_change|`` in
    ``[0.035, 0.055]``, safely above the 0.02 threshold.
  * Each run of length 4 produces exactly **2** flagged rows under the
    "closes a 3-period run" rule — the 3rd and 4th periods of the
    spike. So the reference flag set has exactly 12 rows.
  * Runs are spaced 40 rows apart, far more than the 3-period look-
    back, so there is no cross-run interference.

The strict |pct_change| > 0.02 vs >= 0.02 ambiguity is irrelevant by
construction — no period sits in the (0.005, 0.035) band.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

_N_ROWS = 300
_START_VALUE = 100.0
_CALM_DELTA_MAX = 0.004  # |pct_change| < 0.005 for calm periods
_SPIKE_DELTA_MIN = 0.035
_SPIKE_DELTA_MAX = 0.055
# Each tuple is (start_t, length). The "spike periods" are at
# t = start_t, start_t+1, ..., start_t+length-1 (inclusive).
_SPIKE_RUNS = (
    (20, 4),
    (60, 4),
    (100, 4),
    (150, 4),
    (200, 4),
    (250, 4),
)


def _spike_positions() -> set[int]:
    positions: set[int] = set()
    for start, length in _SPIKE_RUNS:
        for i in range(length):
            positions.add(start + i)
    return positions


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    spike_set = _spike_positions()
    values = [_START_VALUE]
    for t in range(1, _N_ROWS):
        if t in spike_set:
            mag = rng.uniform(_SPIKE_DELTA_MIN, _SPIKE_DELTA_MAX)
            sign = 1 if rng.random() < 0.5 else -1
            delta = sign * mag
        else:
            delta = rng.uniform(-_CALM_DELTA_MAX, _CALM_DELTA_MAX)
        values.append(values[-1] * (1.0 + delta))

    out_path = output_dir / "series.csv"
    with open(out_path, "w") as f:
        f.write("t,value\n")
        for t, v in enumerate(values):
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
