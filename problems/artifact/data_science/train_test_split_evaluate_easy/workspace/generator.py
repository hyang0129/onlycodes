#!/usr/bin/env python3
"""Workspace generator for ``data_science__train_test_split_evaluate_easy``.

Writes ``housing.csv`` with 200 rows and columns ``x1,x2,x3,x4,x5,y``. The
five features are drawn IID from N(0, 1). The target is a linear combination
plus Gaussian noise, so ordinary least squares with ``fit_intercept=True``
recovers a sensible RMSE rather than a degenerate one. Stdlib-only (``random``
and ``math``) for hermeticity at materialize time.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

_N_ROWS = 200
_FEATURE_COLS = ["x1", "x2", "x3", "x4", "x5"]
# Coefficients used to construct y. The agent never sees these; only the
# generated (X, y) pairs are visible.
_TRUE_BETA = [2.0, -1.5, 0.5, 0.1, 0.0]
_TRUE_INTERCEPT = 3.0
_NOISE_STD = 0.5


def _gauss(rng: random.Random) -> float:
    # random.gauss is deterministic given a seeded Random instance.
    return rng.gauss(0.0, 1.0)


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    rows: list[list[float]] = []
    for _ in range(_N_ROWS):
        xs = [_gauss(rng) for _ in _FEATURE_COLS]
        noise = rng.gauss(0.0, _NOISE_STD)
        y = _TRUE_INTERCEPT + sum(b * x for b, x in zip(_TRUE_BETA, xs)) + noise
        rows.append(xs + [y])

    out_path = output_dir / "housing.csv"
    with open(out_path, "w") as f:
        f.write(",".join(_FEATURE_COLS + ["y"]) + "\n")
        for row in rows:
            # 12 significant digits is plenty for ±1e-4 grader tolerance.
            f.write(",".join(f"{v:.12g}" for v in row) + "\n")


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
