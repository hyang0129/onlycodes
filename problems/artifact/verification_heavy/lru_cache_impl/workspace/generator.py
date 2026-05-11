#!/usr/bin/env python3
"""Workspace generator for verification_heavy__lru_cache_impl. Stdlib-only.

Writes ``examples.json``: a seeded sequence of LRU operations plus the expected
get() return value for each get. The agent can replay this against their
implementation. The hidden grader runs its own larger property set.
"""

from __future__ import annotations
import argparse, json, random
from collections import OrderedDict
from pathlib import Path


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    capacity = rng.randint(2, 4)
    cache: "OrderedDict[int, int]" = OrderedDict()

    def ref_put(k, v):
        if k in cache:
            cache.move_to_end(k)
            cache[k] = v
        else:
            if len(cache) >= capacity:
                cache.popitem(last=False)
            cache[k] = v

    def ref_get(k):
        if k not in cache:
            return -1
        cache.move_to_end(k)
        return cache[k]

    ops = []
    for _ in range(20):
        key = rng.randint(1, 6)
        if rng.random() < 0.5:
            value = rng.randint(1, 100)
            ref_put(key, value)
            ops.append({"op": "put", "key": key, "value": value})
        else:
            expected = ref_get(key)
            ops.append({"op": "get", "key": key, "expected": expected})

    payload = {
        "description": (
            "Seeded operation sequence with expected get() returns. Replay "
            "against your LRUCache to develop locally. The hidden grader runs "
            "its own larger property set."
        ),
        "capacity": capacity,
        "ops": ops,
    }
    (output_dir / "examples.json").write_text(json.dumps(payload, indent=2))


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
