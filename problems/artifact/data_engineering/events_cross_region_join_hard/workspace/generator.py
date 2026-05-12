#!/usr/bin/env python3
"""Workspace generator for ``data_engineering__events_cross_region_join_hard``.

Writes four files into the agent's scratch dir:

  * ``users.csv`` — 50 users with integer user_id 1..50, email, tier.
  * ``events_us.jsonl`` — 80 events with fields ``uid``, ``ts`` (epoch s),
    ``evt`` (camel-case).
  * ``events_eu.jsonl`` — 80 events with fields ``userId`` (``u-NN``),
    ``timestamp`` (ISO with tz offset), ``event`` (Title Case With Spaces).
  * ``events_apac.jsonl`` — 80 events with fields ``user_id``
    (``USER_NN``), ``time_local`` (naive ISO; Asia/Tokyo), ``action``
    (already snake_case).

Each region has a small share of (a) orphan user references (id not in
``users.csv``) and (b) typo'd event types, both of which the agent must
drop.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_N_USERS = 50
_N_PER_REGION = 80
_ORPHAN_PROB = 0.10
_BAD_EVT_PROB = 0.08

_TIERS = ["free", "pro", "enterprise"]
_US_EVTS = ["PageView", "AddToCart", "Checkout", "Login", "Logout"]
_EU_EVTS = ["Page View", "Add To Cart", "Checkout", "Login", "Logout"]
_APAC_EVTS = ["page_view", "add_to_cart", "checkout", "login", "logout"]
_BAD_US = ["Clicked", "Browse", "Cartview"]
_BAD_EU = ["Page Show", "Cart Add"]
_BAD_APAC = ["click", "browse", "page_load"]

_DATE_START = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_DATE_SECONDS = 60 * 24 * 3600  # 60 days


def _random_utc_dt(rng: random.Random) -> datetime:
    return _DATE_START + timedelta(seconds=rng.randrange(_DATE_SECONDS))


def _user_id(rng: random.Random) -> int:
    if rng.random() < _ORPHAN_PROB:
        return rng.randint(_N_USERS + 1, _N_USERS + 100)
    return rng.randint(1, _N_USERS)


def _make_users(rng: random.Random) -> list[dict]:
    rows = []
    for n in range(1, _N_USERS + 1):
        rows.append(
            {
                "user_id": str(n),
                "email": f"user{n:03d}@example.com",
                "tier": rng.choice(_TIERS),
            }
        )
    return rows


def _make_us(rng: random.Random) -> list[dict]:
    events = []
    for _ in range(_N_PER_REGION):
        dt_utc = _random_utc_dt(rng)
        uid = _user_id(rng)
        if rng.random() < _BAD_EVT_PROB:
            evt = rng.choice(_BAD_US)
        else:
            evt = rng.choice(_US_EVTS)
        events.append({"uid": uid, "ts": int(dt_utc.timestamp()), "evt": evt})
    return events


def _make_eu(rng: random.Random) -> list[dict]:
    # EU local times alternate between +01:00 (CET) and +02:00 (CEST).
    events = []
    for _ in range(_N_PER_REGION):
        dt_utc = _random_utc_dt(rng)
        offset_hours = rng.choice([1, 2])
        local = dt_utc.astimezone(timezone(timedelta(hours=offset_hours)))
        # ISO with explicit offset, e.g. "2026-01-15T14:23:00+01:00"
        ts = local.strftime("%Y-%m-%dT%H:%M:%S") + (
            f"+{offset_hours:02d}:00" if offset_hours >= 0 else f"-{-offset_hours:02d}:00"
        )
        uid = _user_id(rng)
        if rng.random() < _BAD_EVT_PROB:
            event = rng.choice(_BAD_EU)
        else:
            event = rng.choice(_EU_EVTS)
        events.append({"userId": f"u-{uid}", "timestamp": ts, "event": event})
    return events


def _make_apac(rng: random.Random) -> list[dict]:
    # APAC: Asia/Tokyo, fixed +09:00 (no DST).
    tokyo = timezone(timedelta(hours=9))
    events = []
    for _ in range(_N_PER_REGION):
        dt_utc = _random_utc_dt(rng)
        local = dt_utc.astimezone(tokyo)
        # Naive ISO, no offset.
        time_local = local.strftime("%Y-%m-%dT%H:%M:%S")
        uid = _user_id(rng)
        if rng.random() < _BAD_EVT_PROB:
            action = rng.choice(_BAD_APAC)
        else:
            action = rng.choice(_APAC_EVTS)
        events.append({"user_id": f"USER_{uid}", "time_local": time_local, "action": action})
    return events


def _write_csv(path: Path, rows: list[dict], cols: list[str]) -> None:
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, separators=(",", ":")) + "\n")


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    _write_csv(
        output_dir / "users.csv",
        _make_users(rng),
        ["user_id", "email", "tier"],
    )
    _write_jsonl(output_dir / "events_us.jsonl", _make_us(rng))
    _write_jsonl(output_dir / "events_eu.jsonl", _make_eu(rng))
    _write_jsonl(output_dir / "events_apac.jsonl", _make_apac(rng))


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
