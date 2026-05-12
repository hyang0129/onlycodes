#!/usr/bin/env python3
"""Workspace generator for ``data_engineering__normalize_login_timestamps_easy``.

Writes a single ``login_events.csv`` whose ``login_at`` column mixes two
encodings of the same UTC instant: ISO 8601 with the ``Z`` suffix
(emitted by the ``us-east`` cluster) and bare epoch seconds (emitted by
the ``eu-west`` cluster). The agent must produce a canonical UTC ISO 8601
column.
"""

from __future__ import annotations

import argparse
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REGIONS = ["us-east", "eu-west"]
_NUM_ROWS = 120

_WINDOW_START = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)
_WINDOW_SECONDS = 14 * 24 * 60 * 60  # two-week window


def _format_iso_z(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_epoch_s(t: datetime) -> str:
    return str(int(t.timestamp()))


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    rows: list[dict] = []
    used_offsets: set[int] = set()
    for i in range(_NUM_ROWS):
        # Distinct timestamps so every row sorts unambiguously by event_id.
        while True:
            cand = rng.randrange(_WINDOW_SECONDS)
            if cand not in used_offsets:
                used_offsets.add(cand)
                break
        ts = _WINDOW_START + timedelta(seconds=cand)
        region = rng.choice(_REGIONS)
        if region == "us-east":
            login_at = _format_iso_z(ts)
        else:
            login_at = _format_epoch_s(ts)
        rows.append(
            {
                "event_id": f"evt-{i:06d}",
                "user_id": f"u-{rng.randint(1, 250):05d}",
                "region": region,
                "login_at": login_at,
            }
        )
    rng.shuffle(rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    cols = ["event_id", "user_id", "region", "login_at"]
    with open(output_dir / "login_events.csv", "w", newline="") as fh:
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
