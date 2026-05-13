#!/usr/bin/env python3
"""Workspace generator for ``data_science__regression_metrics_grouped_medium``.

Writes ``predictions.csv`` with 600 rows and columns
``id, group, y_true, y_pred``.

Construction (stdlib only, hermetic at materialize time):

  * Four groups (``alpha``, ``beta``, ``gamma``, ``delta``) with
    different row counts (150 each, totaling 600).
  * Per-group ``y_true`` distribution and per-group prediction bias /
    noise scale differ so the per-group metrics are visibly distinct:
      - alpha: y_true ~ N(10, 2),  noise σ=0.5, no bias
      - beta:  y_true ~ N(20, 3),  noise σ=1.5, bias=+0.3
      - gamma: y_true ~ N(-5, 4),  noise σ=2.0, bias=-0.5
      - delta: y_true ~ N(0,  1),  noise σ=0.2, no bias

  All four groups have enough variance in ``y_true`` (per-group std
  ≥ 1.0 by construction with a comfortable margin at 150 rows) that
  per-group R² denominators are firmly positive — no risk of
  divide-by-zero in the grader.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

_GROUP_SPECS = [
    # (name, n_rows, y_mean, y_std, noise_std, bias)
    ("alpha", 150, 10.0, 2.0, 0.5, 0.0),
    ("beta", 150, 20.0, 3.0, 1.5, 0.3),
    ("gamma", 150, -5.0, 4.0, 2.0, -0.5),
    ("delta", 150, 0.0, 1.0, 0.2, 0.0),
]


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    rows: list[tuple[int, str, float, float]] = []
    next_id = 0
    for name, n_rows, y_mean, y_std, noise_std, bias in _GROUP_SPECS:
        for _ in range(n_rows):
            y_true = rng.gauss(y_mean, y_std)
            y_pred = y_true + bias + rng.gauss(0.0, noise_std)
            rows.append((next_id, name, y_true, y_pred))
            next_id += 1

    # Shuffle so groups are interleaved on disk (forces the agent to
    # actually group rather than slice consecutively).
    rng.shuffle(rows)

    out_path = output_dir / "predictions.csv"
    with open(out_path, "w") as f:
        f.write("id,group,y_true,y_pred\n")
        for rid, name, yt, yp in rows:
            # 12 sig digits is plenty for ±1e-4 grader tolerance.
            f.write(f"{rid},{name},{yt:.12g},{yp:.12g}\n")


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
