#!/usr/bin/env python3
"""Workspace generator for data_processing__funnel_conversion.

Writes ``events.jsonl`` into the output directory: ~20,000 rows across
~2,000 users, with realistic signup-funnel drop-off at each step and
plenty of noise events. Stdlib-only.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

_FUNNEL = ["signup", "verify_email", "onboarding_complete", "first_action", "subscribe"]
_NOISE = ["heartbeat", "page_view", "logout", "login", "settings_open"]

# Drop-off rates between consecutive funnel steps. Realistic SaaS-ish values.
_STEP_PROB = [1.0, 0.72, 0.58, 0.68, 0.35]

_N_USERS = 2_000
_TS_BASE = 1_702_000_000.0
_WEEK = 7 * 24 * 3600.0


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    events: list[dict] = []

    for i in range(_N_USERS):
        user_id = f"u_{i:06d}"
        # ~97% of users signup; a few sneak in only with noise events (edge).
        if rng.random() > 0.97:
            for _ in range(rng.randint(0, 5)):
                events.append({
                    "user_id": user_id,
                    "event": rng.choice(_NOISE),
                    "ts": round(_TS_BASE + rng.uniform(0, _WEEK), 4),
                })
            continue

        signup_ts = _TS_BASE + rng.uniform(0, _WEEK * 0.5)
        events.append({"user_id": user_id, "event": "signup",
                       "ts": round(signup_ts, 4)})

        # Walk the funnel step by step; stop probabilistically.
        cur_ts = signup_ts
        for step_idx in range(1, len(_FUNNEL)):
            if rng.random() > _STEP_PROB[step_idx]:
                break
            cur_ts += rng.uniform(30.0, 24 * 3600.0)
            events.append({
                "user_id": user_id,
                "event": _FUNNEL[step_idx],
                "ts": round(cur_ts, 4),
            })

        # Inject "out-of-order" edge: some users emit first_action BEFORE
        # onboarding_complete, which must disqualify them from first_action.
        # We do this ~5% of the time for users who reached onboarding.
        if rng.random() < 0.05:
            oops_ts = signup_ts + rng.uniform(5, 30)
            events.append({
                "user_id": user_id,
                "event": "first_action",
                "ts": round(oops_ts, 4),
            })

        # Sprinkle noise events for this user.
        for _ in range(rng.randint(0, 6)):
            events.append({
                "user_id": user_id,
                "event": rng.choice(_NOISE),
                "ts": round(signup_ts + rng.uniform(0, _WEEK), 4),
            })

        # Rare duplicate funnel events (e.g. retry) — only *first* should count.
        if rng.random() < 0.08:
            dup_event = rng.choice(_FUNNEL[:3])
            events.append({
                "user_id": user_id,
                "event": dup_event,
                "ts": round(signup_ts + rng.uniform(_WEEK * 0.5, _WEEK), 4),
            })

    rng.shuffle(events)

    out = output_dir / "events.jsonl"
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
