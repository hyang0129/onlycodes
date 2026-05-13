#!/usr/bin/env python3
"""Workspace generator for ``data_science__cohort_ttest_medium``.

Writes ``pairs.csv`` with 150 rows and columns
``subject_id, cohort, before, after``.

Construction (stdlib only, hermetic at materialize time):

  * Three cohorts (``north``, ``south``, ``west``), 50 subjects each.
  * Per-cohort effect on (after - before):
      - north: diff ~ N(+2.0, 1.5)  → strongly positive, sig
      - south: diff ~ N(+0.1, 1.5)  → near-null, NOT sig
      - west:  diff ~ N(-2.0, 1.5)  → strongly negative, sig
  * Within each cohort, ``before`` is drawn from N(50, 5) (cohort-
    agnostic baseline). ``after = before + cohort_diff_draw``.
  * Overall (north + south + west pooled): per-subject diffs average
    ≈ 0.03 with std ≈ 2.3, so the pooled t ≈ 0.16 and p ≈ 0.87 — not
    sig. Wide separation from α=0.05.

The dataset is constructed so per-cohort and pooled p-values are
either ≪ 1e-10 or > 0.7 — no test sits near the α=0.05 boundary.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

_BASELINE_MU = 50.0
_BASELINE_SIGMA = 5.0
_DIFF_SIGMA = 1.5
_COHORTS = [
    # (name, n_subjects, mean_diff)
    ("north", 50, 2.0),
    ("south", 50, 0.1),
    ("west", 50, -2.0),
]


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    rows: list[tuple[int, str, float, float]] = []
    next_id = 0
    for name, n_subj, mean_diff in _COHORTS:
        for _ in range(n_subj):
            before = rng.gauss(_BASELINE_MU, _BASELINE_SIGMA)
            diff = rng.gauss(mean_diff, _DIFF_SIGMA)
            after = before + diff
            rows.append((next_id, name, before, after))
            next_id += 1

    rng.shuffle(rows)

    out_path = output_dir / "pairs.csv"
    with open(out_path, "w") as f:
        f.write("subject_id,cohort,before,after\n")
        for sid, name, b, a in rows:
            f.write(f"{sid},{name},{b:.12g},{a:.12g}\n")


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
