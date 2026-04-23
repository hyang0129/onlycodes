#!/usr/bin/env python3
"""Workspace generator for stateful_reasoning__session_fsm.

Writes session_events.jsonl: a realistic mix of session lifecycles including
happy paths (login -> activity* -> logout), idle expirations (gap > 1800s),
corrupted ids (two logins without logout), and stray activity/logout events.
Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

_N_SESSIONS = 40
_T0 = 1_700_000_000  # arbitrary base unix ts


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)

    # Build events by session, then merge and sort by ts.
    events: list[dict] = []
    sessions = [f"sess_{i:03d}" for i in range(_N_SESSIONS)]

    next_ts = _T0

    for sid in sessions:
        # pick an archetype
        kind = rng.random()
        # step ts forward a bit between sessions so first login bases differ
        base = next_ts + rng.randint(5, 120)
        t = base

        if kind < 0.45:
            # happy path
            events.append({"ts": t, "session_id": sid, "event": "login"})
            for _ in range(rng.randint(1, 8)):
                t += rng.randint(30, 900)  # < 1800 so no expire
                events.append({"ts": t, "session_id": sid, "event": "activity"})
            t += rng.randint(5, 500)
            events.append({"ts": t, "session_id": sid, "event": "logout"})
        elif kind < 0.70:
            # idle expiration
            events.append({"ts": t, "session_id": sid, "event": "login"})
            for _ in range(rng.randint(0, 3)):
                t += rng.randint(30, 900)
                events.append({"ts": t, "session_id": sid, "event": "activity"})
            # big gap -> expired when next event arrives (could be a new login or activity)
            t += rng.randint(2000, 5000)
            if rng.random() < 0.5:
                # re-login after expire (legal, starts a new active session)
                events.append({"ts": t, "session_id": sid, "event": "login"})
                for _ in range(rng.randint(0, 3)):
                    t += rng.randint(30, 900)
                    events.append({"ts": t, "session_id": sid, "event": "activity"})
                if rng.random() < 0.5:
                    t += rng.randint(30, 500)
                    events.append({"ts": t, "session_id": sid, "event": "logout"})
            else:
                # stray activity after expiry (ignored)
                events.append({"ts": t, "session_id": sid, "event": "activity"})
        elif kind < 0.85:
            # corrupted: two logins without intervening logout (and no expiry gap)
            events.append({"ts": t, "session_id": sid, "event": "login"})
            t += rng.randint(30, 500)
            events.append({"ts": t, "session_id": sid, "event": "activity"})
            t += rng.randint(30, 500)
            events.append({"ts": t, "session_id": sid, "event": "login"})  # corrupts
            # further events ignored but still emitted
            t += rng.randint(30, 500)
            events.append({"ts": t, "session_id": sid, "event": "activity"})
        else:
            # stray events: activity/logout for a session that never logged in,
            # followed by an eventual login + logout
            t += rng.randint(10, 200)
            events.append({"ts": t, "session_id": sid, "event": "activity"})
            t += rng.randint(10, 200)
            events.append({"ts": t, "session_id": sid, "event": "logout"})
            t += rng.randint(10, 200)
            events.append({"ts": t, "session_id": sid, "event": "login"})
            t += rng.randint(10, 500)
            events.append({"ts": t, "session_id": sid, "event": "logout"})

        next_ts = t

    # Add a few cross-session interleaved small events by sorting on ts,
    # but resolve ts collisions by bumping (keep strictly increasing).
    events.sort(key=lambda e: e["ts"])
    last = 0
    for e in events:
        if e["ts"] <= last:
            e["ts"] = last + 1
        last = e["ts"]

    path = output_dir / "session_events.jsonl"
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
