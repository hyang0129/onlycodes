#!/usr/bin/env python3
"""Workspace generator for ``data_engineering__dedup_user_profiles_easy``.

Writes a single ``users_raw.csv`` containing user-profile snapshots that
include duplicates of ``(tenant, user_id)``. The agent must dedupe so that
each composite key keeps one row: the latest ``last_updated``, with
``version`` as the deterministic tie-breaker.

Generation rules (chosen to make the task well-defined):

* 3 tenants × 30 users per tenant = 90 distinct ``(tenant, user_id)`` keys.
* Each key has 1..4 rows (rng.randint). Average ~2.5, total ~225 rows.
* For each key, the rows are emitted in *random insertion order* (interleaved
  across the file) so the agent must group, not just look at adjacent rows.
* About 8% of rows have an empty ``email`` field; the rest follow the
  ``first.last@example.com`` convention.
* Names and emails *can* differ between rows of the same key (this models
  the real-world case where the user changed their display name or address
  between updates). The "latest" version is what BI wants.
* Two rows for the same key never share the same ``last_updated``: every
  edit gets a unique timestamp drawn from a 24-hour window. This means the
  ``version`` tie-break is documented in the prompt but never actually fires
  in the generated data — the prompt still demands the rule because the
  agent has no way to know the data is structured this nicely.
"""

from __future__ import annotations

import argparse
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

_TENANTS = ["acme", "globex", "initech"]
_USERS_PER_TENANT = 30
_MIN_ROWS_PER_USER = 1
_MAX_ROWS_PER_USER = 4
_EMPTY_EMAIL_PROB = 0.08

_FIRST_NAMES = [
    "Alex", "Brian", "Cara", "Dani", "Eve", "Felix", "Greta", "Hugo",
    "Ines", "Jane", "Kai", "Lia", "Mia", "Noor", "Owen", "Pia",
    "Quin", "Ravi", "Sara", "Theo", "Uma", "Vik", "Wren", "Xian",
    "Yara", "Zane",
]
_LAST_NAMES = [
    "Allen", "Brown", "Chen", "Davis", "Edwards", "Fischer", "Garcia",
    "Hall", "Iyer", "Jones", "Kim", "Lopez", "Murphy", "Nguyen",
    "Owens", "Patel", "Quinn", "Roy", "Smith", "Tan", "Ueda", "Vance",
    "Wong", "Xu", "Young", "Zhao",
]

_WINDOW_START = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)
_WINDOW_SECONDS = 24 * 60 * 60  # one rolling day


def _format_ts(t: datetime) -> str:
    # Always emit naive UTC with Z suffix (no microseconds, no offset chars).
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_rows(rng: random.Random) -> list[dict]:
    rows: list[dict] = []
    used_seconds: set[int] = set()
    for tenant in _TENANTS:
        for u in range(1, _USERS_PER_TENANT + 1):
            user_id = f"U-{u:05d}"
            n_rows = rng.randint(_MIN_ROWS_PER_USER, _MAX_ROWS_PER_USER)
            # Pick n_rows distinct second offsets within the window so
            # ``last_updated`` is unique within this key.
            offsets: list[int] = []
            while len(offsets) < n_rows:
                cand = rng.randrange(_WINDOW_SECONDS)
                if cand in used_seconds:
                    continue
                used_seconds.add(cand)
                offsets.append(cand)
            offsets.sort()
            base_version = rng.randint(1, 10)
            for i, off in enumerate(offsets):
                first = rng.choice(_FIRST_NAMES)
                last = rng.choice(_LAST_NAMES)
                name = f"{first} {last}"
                if rng.random() < _EMPTY_EMAIL_PROB:
                    email = ""
                else:
                    email = f"{first.lower()}.{last.lower()}@example.com"
                version = base_version + i
                ts = _WINDOW_START + timedelta(seconds=off)
                rows.append(
                    {
                        "tenant": tenant,
                        "user_id": user_id,
                        "name": name,
                        "email": email,
                        "version": str(version),
                        "last_updated": _format_ts(ts),
                    }
                )
    # Shuffle so duplicates of the same key are interleaved across the file.
    rng.shuffle(rows)
    return rows


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    rows = _make_rows(rng)
    cols = ["tenant", "user_id", "name", "email", "version", "last_updated"]
    with open(output_dir / "users_raw.csv", "w", newline="") as fh:
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
    args.output_dir.mkdir(parents=True, exist_ok=True)
    generate(args.output_dir, args.seed)


if __name__ == "__main__":
    main()
