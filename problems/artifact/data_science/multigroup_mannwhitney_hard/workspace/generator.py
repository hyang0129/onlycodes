#!/usr/bin/env python3
"""Workspace generator for ``data_science__multigroup_mannwhitney_hard``.

Writes ``measurements.csv`` with 200 rows and columns
``subject_id, group, value``.

Construction (stdlib only, hermetic at materialize time):

  * Four groups (A, B, C, D), 50 rows each.
  * Two latent "clusters" of identical distribution:
      - Low cluster (A, B): ``value ~ N(10.0, 1.0)``
      - High cluster (C, D): ``value ~ N(15.0, 1.0)``
  * Pairwise expected outcomes under Mann-Whitney U with Bonferroni
    α' = 0.05/6 ≈ 0.0083:
      - A vs B: same distribution → p ~ 0.4..0.8 (NOT sig)
      - C vs D: same distribution → p ~ 0.4..0.8 (NOT sig)
      - A vs C, A vs D, B vs C, B vs D: 5σ separation → p ≪ 1e-15 (sig)
    So 4 of 6 pairs reject, 2 do not. Wide separation from α'.
  * Rows are then shuffled on disk so groups are interleaved.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

_N_PER_GROUP = 50
_GROUPS = [
    # (name, mu, sigma)
    ("A", 10.0, 1.0),
    ("B", 10.0, 1.0),
    ("C", 15.0, 1.0),
    ("D", 15.0, 1.0),
]


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    rows: list[tuple[int, str, float]] = []
    next_id = 0
    for name, mu, sigma in _GROUPS:
        for _ in range(_N_PER_GROUP):
            rows.append((next_id, name, rng.gauss(mu, sigma)))
            next_id += 1
    rng.shuffle(rows)

    out_path = output_dir / "measurements.csv"
    with open(out_path, "w") as f:
        f.write("subject_id,group,value\n")
        for sid, name, v in rows:
            f.write(f"{sid},{name},{v:.12g}\n")


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
