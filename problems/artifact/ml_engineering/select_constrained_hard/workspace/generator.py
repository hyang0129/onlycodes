#!/usr/bin/env python3
"""Workspace generator for ``ml_engineering__select_constrained_*``.

Writes a single CSV of ``N`` synthetic experiment runs with columns

    run_id, dataset, val_acc, params_M, lr, dropout, train_hours

About 12% of the rows satisfy the fixed constraint set declared in
``prompt.md``. The top-20-by-val_acc subset of the satisfying rows is
the canonical reference answer. Difficulty controls **data scale and
near-tie density at the top-20 cutoff**, not the constraints:

  * ``select_constrained_easy``   — N=1_000,   no near-tie cluster
                                    (val_acc gap at the cutoff ≥ 0.05)
  * ``select_constrained_medium`` — N=10_000,  5-row cluster within
                                    ±0.005 val_acc of the cutoff
  * ``select_constrained_hard``   — N=100_000, 10-row cluster within
                                    ±0.002 val_acc of the cutoff

The cluster contains a known boundary: exactly one cluster row is
inside the top-20, the rest are just outside. An agent that reads
val_acc imprecisely (e.g., rounds to 3 decimal places) will pick the
wrong representative from the cluster and lose an F1 point.

Invoked by the harness with ``--seed``, ``--output-dir``, and
``--instance-id``. Standalone-runnable for reference generation.
"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path
from typing import Dict, List, Tuple


# (N_total, frac_satisfying, cluster_size, cluster_half_width)
_DIFFICULTY: Dict[str, Tuple[int, float, int, float]] = {
    "select_constrained_easy":   (1_000,   0.12, 0,  0.0),
    "select_constrained_medium": (10_000,  0.12, 5,  0.005),
    "select_constrained_hard":   (100_000, 0.12, 10, 0.002),
}

# Constraint set — KEEP IN SYNC WITH prompt.md AND grader/hidden.py.
DATASETS_ALL = ["cifar10", "imagenet", "mnist", "svhn", "fashion_mnist"]
DATASETS_OK = {"cifar10", "imagenet"}
PARAMS_M_MAX = 50.0
LR_LOW = 1e-5
LR_HIGH = 1e-3
TRAIN_HOURS_MAX = 24.0
DROPOUT_LOW = 0.1
DROPOUT_HIGH = 0.3

K_SELECT = 20  # how many rows the reference answer contains


def _slug_from_instance_id(instance_id: str) -> str:
    parts = instance_id.split("__", 1)
    return parts[1] if len(parts) == 2 else instance_id


def _gen_satisfying_row(rng: random.Random, run_id: str, val_acc: float) -> dict:
    """Generate one row that satisfies every constraint, with a chosen val_acc."""
    return {
        "run_id": run_id,
        "dataset": rng.choice(sorted(DATASETS_OK)),
        "val_acc": round(val_acc, 6),
        "params_M": round(rng.uniform(2.0, PARAMS_M_MAX), 3),
        "lr": round(10 ** rng.uniform(-5.0, -3.0), 8),
        "dropout": round(rng.uniform(DROPOUT_LOW, DROPOUT_HIGH), 4),
        "train_hours": round(rng.uniform(0.5, TRAIN_HOURS_MAX), 3),
    }


def _gen_violating_row(rng: random.Random, run_id: str) -> dict:
    """Generate one row that violates at least one constraint.

    The violated dimension is chosen uniformly so the violators don't
    cluster on a single constraint. val_acc is drawn from a wider range
    that includes values higher than the top-of-satisfying set; this is
    intentional — violators with high val_acc that fail another
    constraint are the trap rows for agents who only filter on val_acc.
    """
    row = {
        "run_id": run_id,
        "dataset": rng.choice(sorted(DATASETS_OK)),
        "val_acc": round(rng.uniform(0.30, 0.999), 6),
        "params_M": round(rng.uniform(2.0, PARAMS_M_MAX), 3),
        "lr": round(10 ** rng.uniform(-5.0, -3.0), 8),
        "dropout": round(rng.uniform(DROPOUT_LOW, DROPOUT_HIGH), 4),
        "train_hours": round(rng.uniform(0.5, TRAIN_HOURS_MAX), 3),
    }
    # Pick which constraint to violate.
    knob = rng.choice([
        "dataset", "params_M", "lr_low", "lr_high",
        "train_hours", "dropout_low", "dropout_high",
    ])
    if knob == "dataset":
        row["dataset"] = rng.choice([d for d in DATASETS_ALL if d not in DATASETS_OK])
    elif knob == "params_M":
        row["params_M"] = round(rng.uniform(PARAMS_M_MAX + 5.0, 500.0), 3)
    elif knob == "lr_low":
        row["lr"] = round(rng.uniform(1e-8, LR_LOW * 0.5), 10)
    elif knob == "lr_high":
        row["lr"] = round(rng.uniform(LR_HIGH * 2.0, 1.0), 6)
    elif knob == "train_hours":
        row["train_hours"] = round(rng.uniform(TRAIN_HOURS_MAX + 1.0, 200.0), 3)
    elif knob == "dropout_low":
        row["dropout"] = round(rng.uniform(0.0, DROPOUT_LOW * 0.99), 4)
    elif knob == "dropout_high":
        row["dropout"] = round(rng.uniform(DROPOUT_HIGH * 1.01, 0.7), 4)
    return row


def _build_satisfying_val_accs(
    rng: random.Random,
    n_satisfying: int,
    cluster_size: int,
    cluster_half_width: float,
) -> List[float]:
    """Construct val_acc values for the satisfying rows.

    The top (K_SELECT - 1) values are well-separated above 0.95.
    Then a cluster of ``cluster_size`` rows sits within
    ``±cluster_half_width`` of the K_SELECT/(K_SELECT+1) boundary.
    Remaining satisfying rows fall well below the cluster.

    When cluster_size == 0 the boundary has a wide val_acc gap.
    """
    if n_satisfying < K_SELECT + 1:
        raise ValueError(f"need at least {K_SELECT + 1} satisfying rows; got {n_satisfying}")

    # Top K_SELECT - 1 rows: clearly above the cutoff. Use a descending
    # arithmetic sweep from 0.985 down to ~0.95 with small jitter so
    # they're well-separated.
    top_above = sorted(
        [round(0.985 - i * (0.035 / max(1, K_SELECT - 2)) + rng.uniform(-0.0008, 0.0008), 6)
         for i in range(K_SELECT - 1)],
        reverse=True,
    )

    if cluster_size == 0:
        # No near-tie cluster. The K_SELECT-th value sits well above the next.
        cutoff_val = round(rng.uniform(0.93, 0.94), 6)
        below_top = round(cutoff_val - rng.uniform(0.05, 0.08), 6)
        n_below = n_satisfying - K_SELECT
        below = sorted(
            [round(below_top - rng.uniform(0.0, 0.30), 6) for _ in range(n_below)],
            reverse=True,
        )
        return top_above + [cutoff_val] + below

    # Build a cluster of ``cluster_size`` rows tightly around 0.94.
    cluster_center = 0.94
    # Spread the cluster values across [center - half, center + half]
    # so cluster_size values straddle the K_SELECT/(K_SELECT+1) split.
    cluster_vals = []
    for j in range(cluster_size):
        # Linear sweep from -half to +half, slight jitter.
        if cluster_size == 1:
            v = cluster_center
        else:
            t = j / (cluster_size - 1)  # 0 .. 1
            v = cluster_center + (2 * t - 1) * cluster_half_width
        v += rng.uniform(-cluster_half_width * 0.05, cluster_half_width * 0.05)
        cluster_vals.append(round(v, 6))
    cluster_vals.sort(reverse=True)

    # First cluster row enters the top K_SELECT (slot #20), the rest fall just below.
    # So the cluster contributes 1 row above the cutoff and (cluster_size - 1) below.
    n_below = n_satisfying - (K_SELECT - 1) - cluster_size
    if n_below < 0:
        raise ValueError("not enough satisfying rows for cluster + tail")
    below_top = round(min(cluster_vals) - rng.uniform(0.05, 0.08), 6)
    below = sorted(
        [round(below_top - rng.uniform(0.0, 0.30), 6) for _ in range(n_below)],
        reverse=True,
    )
    # Top (K_SELECT - 1) values; then the cluster (size cluster_size);
    # then the tail. The K_SELECT-th selected row is cluster_vals[0].
    return top_above + cluster_vals + below


def generate(output_dir: Path, seed: int, instance_id: str) -> None:
    slug = _slug_from_instance_id(instance_id)
    if slug not in _DIFFICULTY:
        raise ValueError(f"unknown slug {slug!r}; expected one of {list(_DIFFICULTY)}")
    n_total, frac_sat, cluster_size, cluster_half_width = _DIFFICULTY[slug]

    rng = random.Random(seed)
    n_satisfying = int(round(n_total * frac_sat))
    n_violating = n_total - n_satisfying

    val_accs = _build_satisfying_val_accs(rng, n_satisfying, cluster_size, cluster_half_width)

    # run_ids are assigned in a single shuffled namespace so satisfying
    # and violating rows are interleaved on disk.
    run_ids = [f"run_{i:06d}" for i in range(n_total)]
    rng.shuffle(run_ids)
    sat_ids = run_ids[:n_satisfying]
    vio_ids = run_ids[n_satisfying:]

    rows: List[dict] = []
    for rid, va in zip(sat_ids, val_accs):
        rows.append(_gen_satisfying_row(rng, rid, va))
    for rid in vio_ids:
        rows.append(_gen_violating_row(rng, rid))

    # Final on-disk order: shuffled, so val_acc doesn't pre-sort anything.
    rng.shuffle(rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "experiments.csv"
    columns = ["run_id", "dataset", "val_acc", "params_M", "lr", "dropout", "train_hours"]
    with open(out_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


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
