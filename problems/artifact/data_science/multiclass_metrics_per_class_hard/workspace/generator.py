#!/usr/bin/env python3
"""Workspace generator for ``data_science__multiclass_metrics_per_class_hard``.

Writes ``predictions.csv`` with 900 rows and columns ``id, y_true, y_pred``.

Construction (stdlib only, hermetic at materialize time):

  * Four classes (0, 1, 2, 3) with imbalanced supports
    [300, 250, 200, 150] — so macro and weighted averages give
    visibly different numbers.
  * Per-class correctness rate is class-dependent (0.95, 0.80, 0.70,
    0.60). When a row is misclassified, the wrong label is drawn
    uniformly from the other three classes — this guarantees every
    class receives some false positives from every other class, so
    per-class precision and recall denominators are firmly non-zero.
  * Rows are then shuffled on disk so groups are interleaved.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

_CLASS_SUPPORTS = [300, 250, 200, 150]  # classes 0..3
_CORRECT_RATE = [0.95, 0.80, 0.70, 0.60]  # per-class P(y_pred == y_true)
_N_CLASSES = 4


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    rows: list[tuple[int, int, int]] = []
    next_id = 0
    for c in range(_N_CLASSES):
        n_rows = _CLASS_SUPPORTS[c]
        p_correct = _CORRECT_RATE[c]
        wrong_choices = [k for k in range(_N_CLASSES) if k != c]
        for _ in range(n_rows):
            if rng.random() < p_correct:
                y_pred = c
            else:
                y_pred = rng.choice(wrong_choices)
            rows.append((next_id, c, y_pred))
            next_id += 1

    rng.shuffle(rows)

    out_path = output_dir / "predictions.csv"
    with open(out_path, "w") as f:
        f.write("id,y_true,y_pred\n")
        for rid, yt, yp in rows:
            f.write(f"{rid},{yt},{yp}\n")


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
