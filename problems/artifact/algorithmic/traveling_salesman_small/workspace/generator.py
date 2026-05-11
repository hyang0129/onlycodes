#!/usr/bin/env python3
"""Workspace generator for algorithmic__traveling_salesman_small. Stdlib-only.

Writes ``stops.json``: depot + 11 drop-off points uniformly sampled in a
[0, 100] x [0, 100] square (truncated to 4 decimal places so the JSON is
stable).
"""

from __future__ import annotations
import argparse, json, random
from pathlib import Path

_N_POINTS = 12  # depot + 11 stops


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    points = []
    for _ in range(_N_POINTS):
        x = round(rng.uniform(0.0, 100.0), 4)
        y = round(rng.uniform(0.0, 100.0), 4)
        points.append([x, y])
    out = {"depot": 0, "points": points}
    (output_dir / "stops.json").write_text(json.dumps(out, indent=2))


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
