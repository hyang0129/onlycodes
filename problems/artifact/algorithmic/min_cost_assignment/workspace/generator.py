#!/usr/bin/env python3
"""Workspace generator for algorithmic__min_cost_assignment. Stdlib-only.

Writes ``cost_matrix.json``: 20x20 cost matrix with positive integer entries.
Costs are not uniform: every worker has a small "skill" bias toward certain
tasks so the Hungarian algorithm finds a non-trivial assignment.
"""

from __future__ import annotations
import argparse, json, random
from pathlib import Path

_N = 20


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    # Per-worker skill profile: random vector of "natural" tasks. Cost is low
    # for natural tasks and high otherwise — but with enough noise that
    # greedy-by-row is not optimal globally.
    matrix = []
    for w in range(_N):
        natural_set = set(rng.sample(range(_N), k=rng.randint(2, 5)))
        row = []
        for t in range(_N):
            if t in natural_set:
                cost = rng.randint(2, 12)
            else:
                cost = rng.randint(15, 60)
            # global noise
            cost += rng.randint(-2, 4)
            row.append(max(1, cost))
        matrix.append(row)
    out = {"num_workers": _N, "num_tasks": _N, "cost_matrix": matrix}
    (output_dir / "cost_matrix.json").write_text(json.dumps(out, indent=2))


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
