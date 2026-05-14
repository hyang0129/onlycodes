#!/usr/bin/env python3
"""Workspace generator for ``data_science__twogroup_ttest_easy``.

Writes ``measurements.csv`` with 240 rows and columns
``subject_id, group, value``.

Construction (stdlib only, hermetic at materialize time):

  * Control group (n=120): ``value ~ N(10.0, 2.0)``.
  * Treatment group (n=120): ``value ~ N(11.5, 2.5)``.

  The treatment mean is 1.5 above control with comparable std and
  large n, so Welch's t gives |t| ≈ 5 and p ≈ 10^-7 — many orders of
  magnitude below α=0.05. Rows are then shuffled on disk so groups
  are interleaved.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

_N_PER_GROUP = 120
_GROUPS = [
    # (name, mu, sigma)
    ("control", 10.0, 2.0),
    ("treatment", 11.5, 2.5),
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
