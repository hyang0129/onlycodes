#!/usr/bin/env python3
"""Workspace generator for algorithmic__makespan_scheduling. Stdlib-only.

Writes ``jobs.json``: 3 machines, 10 jobs with durations in [4, 30]. Mix of
short and long jobs ensures the optimal assignment is not trivially LPT.
"""

from __future__ import annotations
import argparse, json, random
from pathlib import Path

_N_MACHINES = 3
_N_JOBS = 10


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    # Two clusters: 5 "small" jobs (4-12) + 5 "medium" jobs (15-30). Forces
    # non-trivial balancing.
    durations = []
    for _ in range(5):
        durations.append(rng.randint(4, 12))
    for _ in range(5):
        durations.append(rng.randint(15, 30))
    rng.shuffle(durations)
    out = {"num_machines": _N_MACHINES, "job_durations": durations}
    (output_dir / "jobs.json").write_text(json.dumps(out, indent=2))


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
