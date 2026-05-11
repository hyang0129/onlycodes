#!/usr/bin/env python3
"""Workspace generator for algorithmic__interval_scheduling_weighted. Stdlib-only.

Writes ``requests.json``: 50 booking intervals with overlapping ranges and
varied revenue. Time horizon ~0..200; durations 5..40. Revenue is weakly but
not perfectly correlated with duration — so greedy-by-revenue is wrong.
"""

from __future__ import annotations
import argparse, json, random
from pathlib import Path

_N = 50
_HORIZON = 200


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    requests = []
    for rid in range(_N):
        duration = rng.randint(5, 40)
        start = rng.randint(0, _HORIZON - duration - 1)
        end = start + duration
        # Revenue: noisy ~linear in duration with floor.
        revenue = max(10, int(duration * rng.uniform(2.0, 6.0)) + rng.randint(-15, 25))
        requests.append({"id": rid, "start": start, "end": end, "revenue": revenue})
    out = {"requests": requests}
    (output_dir / "requests.json").write_text(json.dumps(out, indent=2))


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
