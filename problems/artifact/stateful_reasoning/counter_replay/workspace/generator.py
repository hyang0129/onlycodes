#!/usr/bin/env python3
"""Workspace generator for stateful_reasoning__counter_replay.

Writes ``events.jsonl`` with a mix of inc/dec/reset events over a fixed
set of counter names. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

_N_EVENTS = 400
_COUNTERS = [
    "requests.total",
    "requests.2xx",
    "requests.4xx",
    "requests.5xx",
    "queue.depth",
    "cache.hits",
    "cache.misses",
    "errors.5xx",
    "retries.total",
    "sessions.active",
]


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    path = output_dir / "events.jsonl"
    with open(path, "w") as f:
        for _ in range(_N_EVENTS):
            name = rng.choice(_COUNTERS)
            r = rng.random()
            if r < 0.65:
                op = "inc"
                delta = rng.randint(1, 10)
                f.write(json.dumps({"op": op, "name": name, "delta": delta}) + "\n")
            elif r < 0.90:
                op = "dec"
                delta = rng.randint(1, 5)
                f.write(json.dumps({"op": op, "name": name, "delta": delta}) + "\n")
            else:
                op = "reset"
                f.write(json.dumps({"op": op, "name": name}) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--instance-id", type=str, required=False, default="")
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    generate(args.output_dir, args.seed)


if __name__ == "__main__":
    main()
