#!/usr/bin/env python3
"""Workspace generator for algorithmic__coin_change_min. Stdlib-only.

Writes ``request.json``: {denominations: list[int], amount: int}. Most seeds
produce a representable target; the DP correctly returns -1 for the rare seed
where 1 is not in the set and the target is unreachable.
"""

from __future__ import annotations
import argparse, json, random
from pathlib import Path

# Denomination pools the seed picks from. Each pool is realistic and exercises
# different DP branches.
_POOLS = [
    [1, 5, 10, 25],                       # US coins
    [1, 2, 5, 10, 20, 50, 100],           # Euro coins
    [1, 5, 10, 50, 100, 500],             # JPY coins
    [3, 7, 11],                           # No 1 — sometimes unreachable
    [1, 3, 4],                            # Classic "greedy fails" case
    [2, 5, 10, 20, 50],                   # Even denominations only
]


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    denominations = sorted(rng.choice(_POOLS))
    amount = rng.randint(40, 1500)
    out = {"denominations": denominations, "amount": amount}
    (output_dir / "request.json").write_text(json.dumps(out, indent=2))


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
