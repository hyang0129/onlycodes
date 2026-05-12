#!/usr/bin/env python3
"""Workspace generator for ``data_engineering__normalize_order_timestamps_medium``.

Writes a single ``orders.csv`` whose ``placed_at`` column mixes three
encodings of the same UTC instant — ISO 8601 with numeric offset, epoch
milliseconds, and US-slash-date with a named timezone abbreviation — plus
some rows that must be filtered (status=cancelled, or empty placed_at).

Realistic messiness:

* ~6% of surviving rows have whitespace padding around ``placed_at``.
* ~10% of all rows are ``status=cancelled`` (must be dropped regardless of
  whether the timestamp is parseable).
* ~7% of all rows have an empty ``placed_at`` (must be dropped).
* All three timestamp formats reach every region so the agent cannot
  shortcut by branching on ``region``.
"""

from __future__ import annotations

import argparse
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REGIONS = ["na", "eu", "apac"]
_STATUSES = ["placed", "fulfilled"]
_NUM_ROWS = 220
_CANCEL_PROB = 0.10
_EMPTY_TS_PROB = 0.07
_WHITESPACE_PROB = 0.06

_WINDOW_START = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)
_WINDOW_SECONDS = 10 * 24 * 60 * 60  # 10-day window

# Format choices: name → (offset_minutes_from_utc, label) for slash-format,
# or sentinel for the other two formats.
_TZ_TABLE = {
    "UTC": 0,
    "EST": -5 * 60,
    "EDT": -4 * 60,
    "PST": -8 * 60,
    "PDT": -7 * 60,
}
_OFFSETS_FOR_ISO = ["+00:00", "+01:00", "+02:00", "-05:00", "-08:00", "+05:30", "+09:00"]
_FORMATS = ["iso_offset", "epoch_ms", "slash_tz"]


def _format_iso_offset(t_utc: datetime, offset_str: str) -> str:
    sign = 1 if offset_str.startswith("+") else -1
    hh, mm = offset_str[1:].split(":")
    delta = timedelta(hours=int(hh), minutes=int(mm)) * sign
    local = t_utc + delta
    return local.strftime("%Y-%m-%dT%H:%M:%S") + offset_str


def _format_epoch_ms(t_utc: datetime, ms_offset: int) -> str:
    base_ms = int(t_utc.timestamp() * 1000)
    # Add a sub-second jitter; the agent must truncate it back to seconds.
    return str(base_ms + ms_offset)


def _format_slash_tz(t_utc: datetime, tz_name: str) -> str:
    delta = timedelta(minutes=_TZ_TABLE[tz_name])
    local = t_utc + delta
    return local.strftime("%m/%d/%Y %H:%M:%S") + " " + tz_name


def _pad(rng: random.Random, value: str) -> str:
    if rng.random() < _WHITESPACE_PROB and value:
        left = " " * rng.randint(1, 2)
        right = " " * rng.randint(1, 2)
        return left + value + right
    return value


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    rows: list[dict] = []
    used_offsets: set[int] = set()

    for i in range(_NUM_ROWS):
        # Distinct seconds to keep ordering simple.
        while True:
            cand = rng.randrange(_WINDOW_SECONDS)
            if cand not in used_offsets:
                used_offsets.add(cand)
                break
        ts_utc = _WINDOW_START + timedelta(seconds=cand)

        # status & empty-ts decisions are independent of region.
        if rng.random() < _CANCEL_PROB:
            status = "cancelled"
        else:
            status = rng.choice(_STATUSES)

        if rng.random() < _EMPTY_TS_PROB:
            placed_at = ""
        else:
            fmt = rng.choice(_FORMATS)
            if fmt == "iso_offset":
                placed_at = _format_iso_offset(ts_utc, rng.choice(_OFFSETS_FOR_ISO))
            elif fmt == "epoch_ms":
                # 0..999 ms jitter to test that the agent truncates correctly.
                placed_at = _format_epoch_ms(ts_utc, rng.randint(0, 999))
            else:
                placed_at = _format_slash_tz(ts_utc, rng.choice(list(_TZ_TABLE)))
            placed_at = _pad(rng, placed_at)

        rows.append(
            {
                "order_id": f"ord-{i:06d}",
                "region": rng.choice(_REGIONS),
                "status": status,
                "placed_at": placed_at,
            }
        )

    rng.shuffle(rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    cols = ["order_id", "region", "status", "placed_at"]
    with open(output_dir / "orders.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--instance-id", type=str, required=False, default="")
    args = ap.parse_args()
    generate(args.output_dir, args.seed)


if __name__ == "__main__":
    main()
