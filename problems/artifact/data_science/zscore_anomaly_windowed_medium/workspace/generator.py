#!/usr/bin/env python3
"""Workspace generator for ``data_science__zscore_anomaly_windowed_medium``.

Writes ``series.csv`` with 300 rows and columns ``t, value`` in
sequential ``t`` order (0..299).

Construction (stdlib only, hermetic at materialize time):

  * Inliers: ``value ~ N(0, 1)`` rejection-sampled to ``|value| < 2.0``
    so the rolling-window stats stay tight (mean near 0, sample std
    near 1 with bounded fluctuation) and inlier z-scores stay well
    below the |z|=3 threshold.
  * Outliers: 7 spike rows placed at ``t = 40, 80, 120, 160, 200, 240,
    280`` with ``value = 20.0 + small_jitter``. The spacing (40 rows)
    exceeds the window (20), so no spike's window contains a prior
    spike — the trailing-window stats at each spike are pure-inlier
    stats, and every spike's z-score is ≫ 3.
  * Net separation: inlier |z| stays under ~2 with overwhelming
    probability; outlier |z| ≈ 20. The threshold is unambiguous.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

_N_ROWS = 300
_WINDOW = 20  # matches the prompt-pinned window size
_INLIER_CAP = 2.0
_OUTLIER_POSITIONS = (40, 80, 120, 160, 200, 240, 280)
_OUTLIER_VALUE = 20.0
_OUTLIER_JITTER_STD = 0.3


def _bounded_gauss(rng: random.Random, cap: float) -> float:
    while True:
        v = rng.gauss(0.0, 1.0)
        if abs(v) < cap:
            return v


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    outlier_set = set(_OUTLIER_POSITIONS)
    rows: list[tuple[int, float]] = []
    for t in range(_N_ROWS):
        if t in outlier_set:
            v = _OUTLIER_VALUE + rng.gauss(0.0, _OUTLIER_JITTER_STD)
        else:
            v = _bounded_gauss(rng, _INLIER_CAP)
        rows.append((t, v))

    out_path = output_dir / "series.csv"
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
