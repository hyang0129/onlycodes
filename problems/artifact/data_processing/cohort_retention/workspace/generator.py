#!/usr/bin/env python3
"""Workspace generator for data_processing__cohort_retention. Stdlib-only.

Produces signups.csv and activity.csv spanning ~16 weeks with realistic
retention curves (heavy week-0 decay, long-tail stickiness).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import random
from pathlib import Path

_N_SIGNUPS = 8_000
_SPAN_WEEKS = 16
_END_DATE = dt.date(2024, 3, 31)  # a Sunday; max_monday = 2024-03-25


def _weekly_retention_prob(week_offset: int) -> float:
    """Roughly exponential decay with a bump at week 0."""
    if week_offset == 0:
        return 0.92
    return max(0.05, 0.58 * (0.85 ** (week_offset - 1)))


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)

    # Distribute signups across the span. Weight so later weeks have a few
    # more signups (growth).
    start_date = _END_DATE - dt.timedelta(days=_SPAN_WEEKS * 7 - 1)
    span_days = (_END_DATE - start_date).days + 1
    day_weights: list[float] = []
    for i in range(span_days):
        # Slight upward trend + within-week seasonality (fewer weekend signups)
        week_frac = i / span_days
        base = 0.7 + 0.6 * week_frac
        wd = (start_date + dt.timedelta(days=i)).weekday()
        seasonal = 0.7 if wd >= 5 else 1.0
        day_weights.append(base * seasonal)

    total_w = sum(day_weights)
    day_probs = [w / total_w for w in day_weights]

    users: list[tuple[str, dt.date]] = []
    signups_rows = []
    for i in range(_N_SIGNUPS):
        uid = f"user_{i:06d}"
        # Sample an offset day via cumulative weights.
        r = rng.random()
        cum = 0.0
        chosen = 0
        for j, p in enumerate(day_probs):
            cum += p
            if r <= cum:
                chosen = j
                break
        sdate = start_date + dt.timedelta(days=chosen)
        users.append((uid, sdate))
        signups_rows.append((uid, sdate.isoformat()))

    # Write signups.csv
    sp = output_dir / "signups.csv"
    with open(sp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["user_id", "signup_date"])
        for row in signups_rows:
            w.writerow(row)

    # Generate activity. For each user, for each week-offset 0.._SPAN_WEEKS,
    # sample whether they were active; if yes, emit 1-4 activity rows in that
    # week. Activity beyond _END_DATE is clipped.
    activity_rows: list[tuple[str, str]] = []
    for uid, sdate in users:
        sweek_monday = sdate - dt.timedelta(days=sdate.weekday())
        for offset in range(_SPAN_WEEKS + 2):
            week_start = sweek_monday + dt.timedelta(days=offset * 7)
            if week_start > _END_DATE:
                break
            p = _weekly_retention_prob(offset)
            # Individual heterogeneity: half-width noise.
            p += rng.uniform(-0.08, 0.08)
            p = max(0.0, min(1.0, p))
            if rng.random() > p:
                continue
            events = rng.randint(1, 4)
            for _ in range(events):
                day_in_week = rng.randint(0, 6)
                adate = week_start + dt.timedelta(days=day_in_week)
                if adate > _END_DATE:
                    continue
                if adate < sdate:
                    # Don't create activity before signup — unrealistic.
                    continue
                activity_rows.append((uid, adate.isoformat()))

    # Inject "ghost" users — activity without signup — must be filtered out.
    ghost_count = 120
    for i in range(ghost_count):
        gid = f"ghost_{i:04d}"
        for _ in range(rng.randint(1, 5)):
            d = start_date + dt.timedelta(days=rng.randint(0, span_days - 1))
            activity_rows.append((gid, d.isoformat()))

    rng.shuffle(activity_rows)
    ap = output_dir / "activity.csv"
    with open(ap, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["user_id", "activity_date"])
        for row in activity_rows:
            w.writerow(row)


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
