#!/usr/bin/env python3
"""Workspace generator for data_processing__session_window. Stdlib-only."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

_PAGES = [
    "/", "/home", "/catalog", "/catalog/items", "/catalog/items/123",
    "/catalog/items/456", "/search?q=shoes", "/search?q=coat",
    "/cart", "/checkout", "/account", "/account/settings",
    "/blog/post-1", "/blog/post-2", "/help", "/contact",
    "/api/ping",
]

_N_USERS = 1_500
_N_EVENTS = 30_000
_TS_BASE = 1_702_000_000.0
_WEEK = 7 * 24 * 3600.0

_INTRA_GAP_RANGE = (2.0, 800.0)     # within session
_NEW_SESSION_GAP_RANGE = (1801.0, 36 * 3600.0)  # strictly > 1800


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    events: list[dict] = []

    # Allocate a variable number of events per user.
    remaining = _N_EVENTS
    per_user: list[int] = []
    for _ in range(_N_USERS):
        # Heavy-tailed: most users get a handful, a few get dozens.
        n = max(1, int(rng.lognormvariate(2.0, 0.9)))
        per_user.append(min(n, remaining))
        remaining -= per_user[-1]
        if remaining <= 0:
            break
    # Top up so total hits _N_EVENTS.
    while remaining > 0 and per_user:
        idx = rng.randrange(len(per_user))
        per_user[idx] += 1
        remaining -= 1

    for i, n in enumerate(per_user):
        uid = f"u_{i:05d}"
        # Start each user somewhere in the window.
        t = _TS_BASE + rng.uniform(0, _WEEK * 0.6)
        for _ in range(n):
            events.append({
                "user_id": uid,
                "page": rng.choice(_PAGES),
                "ts": round(t, 4),
                "duration_ms": int(rng.uniform(200, 60_000)),
            })
            # Decide inter-event gap: 85% intra-session, 15% new session.
            if rng.random() < 0.85:
                t += rng.uniform(*_INTRA_GAP_RANGE)
            else:
                t += rng.uniform(*_NEW_SESSION_GAP_RANGE)

    # Intentionally include a handful of "exactly 1800.0s" gaps to exercise
    # the "> 1800 starts a new session" boundary.
    rng_boundary = random.Random(seed + 1)
    for _ in range(20):
        uid = f"u_{rng_boundary.randrange(len(per_user)):05d}"
        base_ts = _TS_BASE + rng_boundary.uniform(_WEEK * 0.6, _WEEK * 0.95)
        events.append({"user_id": uid, "page": "/boundary", "ts": round(base_ts, 4),
                       "duration_ms": 500})
        events.append({"user_id": uid, "page": "/boundary", "ts": round(base_ts + 1800.0, 4),
                       "duration_ms": 500})

    rng.shuffle(events)

    out = output_dir / "pageviews.jsonl"
    with open(out, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


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
