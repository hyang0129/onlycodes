#!/usr/bin/env python3
"""Workspace generator for ``data_engineering__normalize_audit_log_dedup_hard``.

Writes three audit-log shards (``audit_alpha.csv``, ``audit_beta.csv``,
``audit_gamma.csv``) whose ``recorded_at`` column mixes four timestamp
formats and includes deliberately malformed rows that the agent must
drop. The same ``(entity_id, action)`` pair appears in 1..3 shards, so
the agent must also dedup by composite key after normalization.

Realistic messiness:

* Each format reaches every shard with non-trivial weight.
* ~7% of rows have a malformed ``recorded_at`` (must be dropped).
* ~5% of valid timestamps have whitespace padding (must be stripped).
* Duplicates: ~40% of ``(entity_id, action)`` keys appear in 2 shards,
  ~15% in 3 shards. The remaining ~45% appear in exactly 1 shard.
* The winner's timestamp is chosen by the latest UTC instant; tie →
  lexicographically smallest source_shard. Within a key, the same shard
  never appears twice, so the (timestamp, shard) tuple is unique.
"""

from __future__ import annotations

import argparse
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SHARDS = ["alpha", "beta", "gamma"]
_ACTIONS = ["create", "update", "delete", "archive"]
_NUM_ENTITIES = 70

_MALFORMED_PROB = 0.07
_WHITESPACE_PROB = 0.05

_WINDOW_START = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)
_WINDOW_SECONDS = 10 * 24 * 60 * 60

_ISO_OFFSETS = ["+00:00", "+01:00", "+02:00", "+05:30", "+09:00", "-05:00", "-08:00"]
_FORMATS = ["iso_z", "iso_offset", "epoch_ms", "naive_utc"]

_MALFORMED_VALUES = [
    "",
    "not-a-time",
    "2026-13-01T00:00:00Z",  # month 13 → strict parse fails
    "2026-02-30T00:00:00Z",  # Feb 30 → strict parse fails
    "1743514025",  # 10-digit epoch seconds → wrong length for ms
    "17435140251234",  # 14-digit → wrong length for ms
    "2026/04/01 14:00:00",
    "April 1 2026",
    "2026-04-01",
]


def _format_iso_z(t_utc: datetime) -> str:
    return t_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_iso_offset(t_utc: datetime, offset_str: str) -> str:
    sign = 1 if offset_str.startswith("+") else -1
    hh, mm = offset_str[1:].split(":")
    delta = timedelta(hours=int(hh), minutes=int(mm)) * sign
    local = t_utc + delta
    return local.strftime("%Y-%m-%dT%H:%M:%S") + offset_str


def _format_epoch_ms(t_utc: datetime, ms_jitter: int) -> str:
    base_ms = int(t_utc.timestamp() * 1000)
    return str(base_ms + ms_jitter)


def _format_naive_utc(t_utc: datetime) -> str:
    return t_utc.strftime("%Y-%m-%d %H:%M:%S")


def _encode_ts(rng: random.Random, t_utc: datetime) -> str:
    fmt = rng.choice(_FORMATS)
    if fmt == "iso_z":
        return _format_iso_z(t_utc)
    if fmt == "iso_offset":
        return _format_iso_offset(t_utc, rng.choice(_ISO_OFFSETS))
    if fmt == "epoch_ms":
        return _format_epoch_ms(t_utc, rng.randint(0, 999))
    return _format_naive_utc(t_utc)


def _pad(rng: random.Random, value: str) -> str:
    if value and rng.random() < _WHITESPACE_PROB:
        left = " " * rng.randint(1, 2)
        right = " " * rng.randint(1, 2)
        return left + value + right
    return value


def _decide_shard_set(rng: random.Random) -> list[str]:
    """Return the shard subset for one (entity, action) key."""
    r = rng.random()
    if r < 0.15:
        return ["alpha", "beta", "gamma"]
    if r < 0.55:
        return rng.sample(_SHARDS, 2)
    return [rng.choice(_SHARDS)]


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    output_dir.mkdir(parents=True, exist_ok=True)

    # rows_by_shard[shard_name] -> list[dict]
    rows_by_shard: dict[str, list[dict]] = {s: [] for s in _SHARDS}
    used_offsets: set[int] = set()

    rec_counters = {s: 0 for s in _SHARDS}

    for ent_idx in range(1, _NUM_ENTITIES + 1):
        entity_id = f"ent-{ent_idx:05d}"
        # 1..3 distinct actions per entity, drawn from _ACTIONS.
        n_actions = rng.randint(1, 3)
        actions = rng.sample(_ACTIONS, n_actions)
        for action in actions:
            shards = _decide_shard_set(rng)
            # Pick distinct second-offsets per (entity, action) so that
            # each (entity, action, shard) gets a unique UTC instant and
            # (timestamp, shard) tie-break never actually fires.
            offsets: list[int] = []
            while len(offsets) < len(shards):
                cand = rng.randrange(_WINDOW_SECONDS)
                if cand in used_offsets:
                    continue
                used_offsets.add(cand)
                offsets.append(cand)
            offsets.sort()  # deterministic order; shard-ts pairing below is random
            rng.shuffle(offsets)
            for shard, off in zip(shards, offsets):
                rec_counters[shard] += 1
                record_id = f"rec-{shard}-{rec_counters[shard]:06d}"
                t_utc = _WINDOW_START + timedelta(seconds=off)
                # ~7% of rows get a malformed timestamp.
                if rng.random() < _MALFORMED_PROB:
                    recorded_at = rng.choice(_MALFORMED_VALUES)
                else:
                    recorded_at = _encode_ts(rng, t_utc)
                recorded_at = _pad(rng, recorded_at)
                rows_by_shard[shard].append(
                    {
                        "record_id": record_id,
                        "entity_id": entity_id,
                        "action": action,
                        "recorded_at": recorded_at,
                        "source_shard": shard,
                    }
                )

    cols = ["record_id", "entity_id", "action", "recorded_at", "source_shard"]
    for shard in _SHARDS:
        rng.shuffle(rows_by_shard[shard])
        with open(output_dir / f"audit_{shard}.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
            w.writeheader()
            for r in rows_by_shard[shard]:
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
