#!/usr/bin/env python3
"""Workspace generator for ml_engineering__curve_queries_{easy,medium,hard}.

Writes ``experiments.csv`` with columns: step, run_id, train_loss, val_loss, lr
in (run_id, step) order. 50 parallel training runs, each with ``steps_per_run``
rows. ~30% of runs (15 of 50) exhibit late-stage overfitting: val_loss
decreases normally then climbs after a randomly chosen onset step.

Difficulty parameters (selected by --instance-id slug):

  * curve_queries_easy   — 50 runs × 2 000 steps  (~5 MB CSV,  1 query)
  * curve_queries_medium — 50 runs × 20 000 steps (~50 MB CSV, 3 queries)
  * curve_queries_hard   — 50 runs × 40 000 steps (~100 MB CSV, 5 queries)

Loss trajectories: exponential decay toward a per-run floor. Noise is
proportional to current loss level (1% relative), so it is large early and
negligibly small at convergence. This prevents false-positive overfit detection
in the grader.

The mapping from (seed, instance_id) → per-run parameters is fully
deterministic. A master RNG chooses which 15 runs are overfit; each run
gets its own derived RNG so per-run values are independent of run order.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from pathlib import Path

_DIFFICULTY: dict[str, dict] = {
    "curve_queries_easy":   {"n_runs": 50, "steps_per_run":  2_000},
    "curve_queries_medium": {"n_runs": 50, "steps_per_run": 20_000},
    "curve_queries_hard":   {"n_runs": 50, "steps_per_run": 40_000},
}
_N_OVERFIT = 15  # 30% of 50 runs


def _slug(instance_id: str) -> str:
    parts = instance_id.split("__", 1)
    return parts[1] if len(parts) == 2 else instance_id


def generate(output_dir: Path, seed: int, instance_id: str) -> None:
    slug = _slug(instance_id)
    if slug not in _DIFFICULTY:
        raise ValueError(f"unknown slug {slug!r}; expected one of {list(_DIFFICULTY)}")
    params = _DIFFICULTY[slug]
    n_runs: int = params["n_runs"]
    steps_per_run: int = params["steps_per_run"]

    master = random.Random(seed)
    overfit_set: set[int] = set(master.sample(range(n_runs), _N_OVERFIT))

    out_path = output_dir / "experiments.csv"
    with open(out_path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["step", "run_id", "train_loss", "val_loss", "lr"])

        for i in range(n_runs):
            run_id = f"run_{i:02d}"
            rng = random.Random((seed * 1_000_003) ^ (i * 2_654_435_761) & 0xFFFF_FFFF)

            floor = rng.uniform(0.40, 0.80)
            gap = floor * 0.15          # val_loss > train_loss offset at convergence
            amplitude = floor * rng.uniform(3.5, 5.5)   # initial loss above floor
            lr = math.exp(rng.uniform(math.log(1e-4), math.log(1e-2)))

            # Decay rate: amplitude decays to 5% of its initial value by 75% of steps.
            # Solving: amplitude * exp(-decay * 0.75 * steps) = 0.05 * amplitude
            #   → decay = log(20) / (0.75 * steps_per_run)
            k_star = 0.75 * steps_per_run
            decay = math.log(20.0) / k_star

            is_overfit = i in overfit_set
            if is_overfit:
                overfit_onset = round(rng.uniform(0.60, 0.80) * steps_per_run)
                # Climb rate: val_loss reaches 1.20 × best within 10% of steps after onset.
                # best_approx ≈ floor + gap at convergence.
                best_approx = floor + gap
                overfit_rate = (0.20 * best_approx) / (0.10 * steps_per_run)
            else:
                overfit_onset = steps_per_run + 1   # never triggers
                overfit_rate = 0.0

            # Iterative factor avoids calling exp() per step (2M calls for hard).
            factor = math.exp(-decay)
            cur_factor = factor   # = exp(-decay * 1) at step 1

            for s in range(1, steps_per_run + 1):
                base_train = floor + amplitude * cur_factor
                cur_factor *= factor

                # 1% relative noise: large when loss is high, negligible at convergence.
                noise_t = 0.01 * base_train
                train_loss = max(floor * 0.50, base_train + rng.gauss(0.0, noise_t))

                base_val = base_train + gap
                val_loss = max(base_val * 0.50, base_val + rng.gauss(0.0, 0.01 * base_val))

                if is_overfit and s > overfit_onset:
                    val_loss += overfit_rate * (s - overfit_onset)

                writer.writerow([s, run_id, f"{train_loss:.6f}", f"{val_loss:.6f}", f"{lr:.8f}"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--instance-id", type=str, required=True)
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    generate(args.output_dir, args.seed, args.instance_id)


if __name__ == "__main__":
    main()
