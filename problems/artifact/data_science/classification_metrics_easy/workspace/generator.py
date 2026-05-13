#!/usr/bin/env python3
"""Workspace generator for ``data_science__classification_metrics_easy``.

Writes ``predictions.csv`` with 500 rows and columns ``id, y_true, y_pred``.

Construction (stdlib only, hermetic at materialize time):

  * ``y_true`` ~ Bernoulli(0.4) (so the positive class is the minority,
    making precision/recall meaningfully different from accuracy).
  * ``y_pred = y_true`` with probability 0.85, else ``1 - y_true``. This
    gives a confusion matrix with all four cells non-zero (TP, FP, FN, TN
    > 0) so precision, recall, and F1 are all well-defined.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

_N_ROWS = 500
_POS_RATE = 0.4
_FLIP_PROB = 0.15


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    rows: list[tuple[int, int, int]] = []
    for i in range(_N_ROWS):
        y_true = 1 if rng.random() < _POS_RATE else 0
        if rng.random() < _FLIP_PROB:
            y_pred = 1 - y_true
        else:
            y_pred = y_true
        rows.append((i, y_true, y_pred))

    out_path = output_dir / "predictions.csv"
    with open(out_path, "w") as f:
        f.write("id,y_true,y_pred\n")
        for row in rows:
            f.write(f"{row[0]},{row[1]},{row[2]}\n")


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
