#!/usr/bin/env python3
"""Workspace generator for ``data_science__iqr_anomaly_flagging_easy``.

Writes ``measurements.csv`` with 300 rows and columns ``id, value``.

Construction (stdlib only, hermetic at materialize time):

  * 285 inlier rows: ``value`` drawn from N(0, 1) but **rejection-
    sampled to |value| < 2.5**, so every inlier sits comfortably
    inside the ~[-3, +3] Tukey fence implied by the resulting Q1/Q3.
  * 15 outlier rows placed at well-separated extremes: 8 at value ≈ -10
    (with small jitter) and 7 at value ≈ +10 (with small jitter). All
    outliers are several IQRs outside the fence.
  * Net effect: the unflagged-max |value| ≈ 2.5 and the flagged-min
    |value| ≈ 9.5, so the cutoff is completely unambiguous regardless
    of which standard quantile interpolation is chosen.
  * `id` is assigned as 1000 + position in the un-shuffled list (so
    ids are sparse and the agent must use the column, not row index).
  * Rows are then shuffled on disk so outliers are interleaved.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

_N_INLIERS = 285
_N_NEG_OUTLIERS = 8
_N_POS_OUTLIERS = 7
_OUTLIER_NEG_MEAN = -10.0
_OUTLIER_POS_MEAN = 10.0
_OUTLIER_JITTER_STD = 0.3
_ID_OFFSET = 1000
_INLIER_ABS_CAP = 2.5  # rejection-sample inliers to |value| < this


def _bounded_gauss(rng: random.Random, cap: float) -> float:
    while True:
        v = rng.gauss(0.0, 1.0)
        if abs(v) < cap:
            return v


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    rows: list[tuple[int, float]] = []
    next_id = _ID_OFFSET

    for _ in range(_N_INLIERS):
        rows.append((next_id, _bounded_gauss(rng, _INLIER_ABS_CAP)))
        next_id += 1
    for _ in range(_N_NEG_OUTLIERS):
        rows.append(
            (next_id, _OUTLIER_NEG_MEAN + rng.gauss(0.0, _OUTLIER_JITTER_STD))
        )
        next_id += 1
    for _ in range(_N_POS_OUTLIERS):
        rows.append(
            (next_id, _OUTLIER_POS_MEAN + rng.gauss(0.0, _OUTLIER_JITTER_STD))
        )
        next_id += 1

    rng.shuffle(rows)

    out_path = output_dir / "measurements.csv"
    with open(out_path, "w") as f:
        f.write("id,value\n")
        for rid, val in rows:
            f.write(f"{rid},{val:.12g}\n")


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
