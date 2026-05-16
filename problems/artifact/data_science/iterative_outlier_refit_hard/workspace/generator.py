#!/usr/bin/env python3
"""Workspace generator for ``data_science__iterative_outlier_refit_hard``.

Writes ``data.csv`` with 500 rows and columns ``x1, x2, x3, y``.

Construction (stdlib only, hermetic at materialize time):

  * Three independent features ``x1, x2, x3`` ~ N(0, 1).
  * True linear model:
        y_true(i) = 3.0 + 2.0*x1(i) - 1.5*x2(i) + 0.5*x3(i)
  * Inlier rows (490 of 500): observation noise drawn from
        Uniform(-0.3, 0.3)
    so every inlier residual against the true model has |r| ≤ 0.3.
  * Outlier rows (10 of 500): observation noise is a fixed shift of
    ±6.0 (alternating signs by position). The outlier rows are placed
    at deterministic positions ``[49, 99, 149, 199, 249, 299, 349, 399,
    449, 499]`` with signs ``[+, -, +, -, +, -, +, -, +, -]`` so the
    outlier residuals sum to zero — the OLS fit on the full data
    is approximately unbiased for the intercept and coefficients.

Separation guarantee (why the |z|>3.0 threshold is unambiguous):

  * Variance contribution per row from inliers: 0.3² / 3 = 0.03.
  * Variance contribution per row from outliers: 6.0² = 36.0.
  * Iteration 1 sigma² ≈ (490·0.03 + 10·36) / 500 ≈ 0.749
    →  sigma ≈ 0.865.
  * Inlier |z| ≤ 0.3 / 0.865 ≈ 0.35  (well below 2.0).
  * Outlier |z| ≈ 6.0 / 0.865 ≈ 6.93  (well above 5.0).
  * After dropping outliers, sigma collapses to ≈ 0.17,
    so outlier |z| balloons further while inlier |z| stays well
    below 2.0.

If a future generator edit narrows this separation (e.g. raising the
inlier noise scale, shrinking the outlier shift, or unbalancing the
outlier sign distribution so the OLS fit shifts noticeably), the
grader's threshold check may become ambiguous; re-derive the reference
output and inspect the per-row z-scores.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

_N_ROWS = 500
_FEATURE_COLS = ["x1", "x2", "x3"]
_BETA = {"x1": 2.0, "x2": -1.5, "x3": 0.5}
_INTERCEPT = 3.0
_INLIER_NOISE_HALFRANGE = 0.3
_OUTLIER_SHIFT = 6.0
# Ten deterministic outlier positions; alternating signs keep mean
# outlier residual at zero so the OLS fit on full data is unbiased.
_OUTLIER_POSITIONS = [49, 99, 149, 199, 249, 299, 349, 399, 449, 499]
_OUTLIER_SIGNS = [+1, -1, +1, -1, +1, -1, +1, -1, +1, -1]


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)

    sign_by_index = dict(zip(_OUTLIER_POSITIONS, _OUTLIER_SIGNS))

    xs: list[list[float]] = []
    ys: list[float] = []
    for i in range(_N_ROWS):
        row = [rng.gauss(0.0, 1.0) for _ in _FEATURE_COLS]
        y_true = _INTERCEPT + sum(
            _BETA[col] * v for col, v in zip(_FEATURE_COLS, row)
        )
        if i in sign_by_index:
            noise = sign_by_index[i] * _OUTLIER_SHIFT
        else:
            noise = rng.uniform(-_INLIER_NOISE_HALFRANGE, _INLIER_NOISE_HALFRANGE)
        xs.append(row)
        ys.append(y_true + noise)

    out_path = output_dir / "data.csv"
    with open(out_path, "w") as f:
        f.write(",".join(_FEATURE_COLS + ["y"]) + "\n")
        for row, y in zip(xs, ys):
            f.write(",".join(f"{v:.12g}" for v in row + [y]) + "\n")


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
