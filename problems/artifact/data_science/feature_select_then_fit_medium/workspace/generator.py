#!/usr/bin/env python3
"""Workspace generator for ``data_science__feature_select_then_fit_medium``.

Writes ``signals.csv`` with 1000 rows and columns ``x1..x10,y``.

Construction (stdlib only, hermetic at materialize time):

  * Four latent signals ``v1, v2, v3, v4`` ~ N(0, 1) IID.
  * Signal features (correlated with y): ``x1, x3, x5, x7``. Each signal
    feature is a noisy view of one latent vector. The noise scales are
    chosen so each signal feature has Pearson |r| with y in the
    ~0.45..0.7 range, well above the 0.30 threshold and well outside the
    (0.15, 0.45) borderline band.
  * Noise features (uncorrelated with y in construction): ``x2, x4, x6, x8,
    x9, x10``. Each is an independent N(0, 1) vector. With 1000 rows the
    expected |r| of an independent N(0, 1) feature with y is ~0/sqrt(1000)
    ≈ 0.032 (std), so |r| > 0.15 is astronomically unlikely.
  * ``y = 1.0*v1 + 0.8*v2 + 1.2*v3 + 0.6*v4 + 0.3*eps`` where eps ~ N(0, 1)
    is residual noise. The agent never sees the latents — only x1..x10 and
    y are in the CSV.

The construction is verified at task-authoring time (see the reference-output
derivation in the PR). If a future generator edit breaks the wide-separation
guarantee, the grader's threshold check will become ambiguous; rerun the
reference derivation and inspect the per-feature |r| values.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

_N_ROWS = 1000
_FEATURE_COLS = [f"x{i}" for i in range(1, 11)]
_SIGNAL_INDICES = (1, 3, 5, 7)  # 1-based: x1, x3, x5, x7 are signal columns
_NOISE_INDICES = (2, 4, 6, 8, 9, 10)
# Per-signal observation noise (smaller → higher |r| with y). Tuned so each
# signal feature has |r| ≈ 0.47 — comfortably above the 0.30 selection
# threshold and outside the (0.20, 0.40) borderline band.
_SIGNAL_NOISE_SCALE = {1: 0.3, 3: 0.3, 5: 0.3, 7: 0.3}
# Per-latent weight in y. Uniform weights give all four signal features the
# same expected |r| with y, simplifying the separation invariant.
_LATENT_WEIGHT = {1: 1.0, 3: 1.0, 5: 1.0, 7: 1.0}
_Y_NOISE_SCALE = 0.3


def _gauss_vec(rng: random.Random, n: int) -> list[float]:
    return [rng.gauss(0.0, 1.0) for _ in range(n)]


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)

    # Four independent latent signals, one per "true" predictor.
    latents = {i: _gauss_vec(rng, _N_ROWS) for i in _SIGNAL_INDICES}
    # Per-signal observation noise (one independent vector per signal feature).
    sig_noise = {i: _gauss_vec(rng, _N_ROWS) for i in _SIGNAL_INDICES}
    # Per-noise-feature vector (independent of everything).
    noise_feats = {i: _gauss_vec(rng, _N_ROWS) for i in _NOISE_INDICES}
    # Target-construction residual.
    eps = _gauss_vec(rng, _N_ROWS)

    cols: dict[str, list[float]] = {}
    for i in _SIGNAL_INDICES:
        scale = _SIGNAL_NOISE_SCALE[i]
        cols[f"x{i}"] = [latents[i][r] + scale * sig_noise[i][r] for r in range(_N_ROWS)]
    for i in _NOISE_INDICES:
        cols[f"x{i}"] = noise_feats[i]

    y_vals = []
    for r in range(_N_ROWS):
        v = 0.0
        for i in _SIGNAL_INDICES:
            v += _LATENT_WEIGHT[i] * latents[i][r]
        v += _Y_NOISE_SCALE * eps[r]
        y_vals.append(v)

    out_path = output_dir / "signals.csv"
    with open(out_path, "w") as f:
        f.write(",".join(_FEATURE_COLS + ["y"]) + "\n")
        for r in range(_N_ROWS):
            row = [cols[c][r] for c in _FEATURE_COLS] + [y_vals[r]]
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
