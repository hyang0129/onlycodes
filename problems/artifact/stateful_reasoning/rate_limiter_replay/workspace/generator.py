#!/usr/bin/env python3
"""Workspace generator for stateful_reasoning__rate_limiter_replay.

Writes requests.jsonl: interleaved API requests across ~30 users with
tiered quotas. Traffic shapes include bursts (for 'free' users, these
cause rejections), steady streams (for 'pro'/'enterprise' users, mostly
accepted), and user tier changes mid-stream. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

_N_USERS = 30
_N_REQ = 1200
_T0 = 1_700_000_000


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)

    users = [f"u{i:03d}" for i in range(_N_USERS)]
    # Assign tiers (mostly free, some pro, few enterprise)
    tiers = {}
    for u in users:
        r = rng.random()
        if r < 0.6:
            tiers[u] = "free"
        elif r < 0.9:
            tiers[u] = "pro"
        else:
            tiers[u] = "enterprise"

    # Build events
    events: list[dict] = []
    t = _T0
    rid = 0

    # Mix of bursts and spread traffic
    for _ in range(_N_REQ):
        rid += 1
        # Advance time most of the time by 0-10s, occasionally bigger jump
        r = rng.random()
        if r < 0.85:
            t += rng.randint(0, 10)
        else:
            t += rng.randint(20, 120)

        user = rng.choice(users)

        # Rare tier change
        if rng.random() < 0.01:
            tiers[user] = rng.choice(["free", "pro", "enterprise"])

        events.append({
            "request_id": f"req_{rid:06d}",
            "ts": t,
            "user_id": user,
            "tier": tiers[user],
        })

    # Also inject some deliberate bursts for free users to ensure rejections
    free_users = [u for u, tier in tiers.items() if tier == "free"]
    if free_users:
        burst_user = rng.choice(free_users)
        burst_ts = _T0 + rng.randint(100, 500)
        for _ in range(12):
            rid += 1
            events.append({
                "request_id": f"req_{rid:06d}",
                "ts": burst_ts,
                "user_id": burst_user,
                "tier": "free",
            })

    # Sort by ts, stable (preserves insertion order for ties)
    events.sort(key=lambda e: e["ts"])

    path = output_dir / "requests.jsonl"
    with open(path, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


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
