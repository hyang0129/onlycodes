#!/usr/bin/env python3
"""Workspace generator for ``data_engineering__dedup_event_log_priority_hard``.

Writes three audit-log shards (``events_alpha.csv``, ``events_beta.csv``,
``events_gamma.csv``) populated with overlapping events that exercise:

  * **Status precedence** ladder (``COMMITTED > RETRIED > PENDING > FAILED``).
  * **Version** tie-break.
  * **Received-at** tie-break.
  * **Source-node** tie-break.
  * **Mixed timestamp formats** (ISO 8601 with offset, epoch milliseconds,
    naive ``YYYY-MM-DD HH:MM:SS.fff``).
  * **`v`-prefixed versions** (~25% of rows).
  * **Supersedes chains** — ~12% of logical events have a ``supersedes_event_id``
    pointer to a *different* logical event (different composite key) that
    must be removed entirely from the output.

Generation is fully deterministic under the seed.
"""

from __future__ import annotations

import argparse
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

_TENANTS = ["acme", "globex", "initech", "umbrella"]
_ENTITIES_PER_TENANT = 30
_EVENT_KINDS = ["created", "updated", "deleted", "archived"]
_STATUSES = ["COMMITTED", "RETRIED", "PENDING", "FAILED"]
_SHARDS = ["alpha", "beta", "gamma"]
_FILES = {s: f"events_{s}.csv" for s in _SHARDS}

_WINDOW_START = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_WINDOW_SECONDS = 30 * 24 * 3600  # 30 days

_TS_FORMATS = ("iso_offset", "epoch_ms", "naive_utc")
_OFFSETS = [0, 60, -60, 120, -120, 330, -300]  # minutes


def _format_iso_with_offset(t_utc: datetime, offset_min: int) -> str:
    """Render ``t_utc`` as an ISO 8601 string in the given offset zone."""
    tz = timezone(timedelta(minutes=offset_min))
    t_local = t_utc.astimezone(tz)
    if offset_min == 0:
        return t_local.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    sign = "+" if offset_min >= 0 else "-"
    a = abs(offset_min)
    return t_local.strftime("%Y-%m-%dT%H:%M:%S") + f"{sign}{a // 60:02d}:{a % 60:02d}"


def _format_epoch_ms(t_utc: datetime, ms: int) -> str:
    """Render ``t_utc`` (with the given millisecond fragment) as a 13-digit
    epoch-millis integer string."""
    base = int(t_utc.replace(microsecond=0).timestamp())
    return str(base * 1000 + ms)


def _format_naive_utc(t_utc: datetime, ms: int) -> str:
    """Render ``t_utc`` as ``YYYY-MM-DD HH:MM:SS.fff`` (millisecond
    precision, no timezone marker)."""
    return t_utc.strftime("%Y-%m-%d %H:%M:%S") + f".{ms:03d}"


def _format_received_at(rng: random.Random, t_utc: datetime, ms: int) -> str:
    """Format ``t_utc`` (with the millisecond fragment ``ms``) in one of
    three randomly chosen wire formats.

    ISO-with-offset rows are emitted at second resolution (the prompt's
    ISO branch does not carry millis), so ``ms`` is ignored on that path.
    """
    fmt = rng.choice(_TS_FORMATS)
    if fmt == "iso_offset":
        offset_min = rng.choice(_OFFSETS)
        return _format_iso_with_offset(t_utc, offset_min)
    if fmt == "epoch_ms":
        return _format_epoch_ms(t_utc, ms)
    return _format_naive_utc(t_utc, ms)


def _format_version(rng: random.Random, n: int) -> str:
    if rng.random() < 0.25:
        return f"v{n}"
    return str(n)


def _make_event_id(rng: random.Random, used: set[str]) -> str:
    while True:
        eid = "evt-" + "".join(rng.choices("0123456789abcdef", k=8))
        if eid not in used:
            used.add(eid)
            return eid


def _pick_tenant_entity_kind(rng: random.Random) -> tuple[str, str, str]:
    t = rng.choice(_TENANTS)
    e = f"ent-{rng.randint(1, _ENTITIES_PER_TENANT):04d}"
    k = rng.choice(_EVENT_KINDS)
    return t, e, k


def _make_logical_event(
    rng: random.Random,
    used_event_ids: set[str],
    used_seconds: set[int],
    composite_key: tuple[str, str, str],
) -> tuple[str, list[dict]]:
    """Create 1..3 candidate rows for one logical event (one composite key).

    All rows for the same logical event share the same ``event_id``. Each
    row picks its own status / version / shard / timestamp.
    """
    eid = _make_event_id(rng, used_event_ids)
    n_replicas = rng.randint(1, 3)
    shards_used = rng.sample(_SHARDS, n_replicas)
    rows: list[dict] = []
    for sh in shards_used:
        # Each replica gets a UNIQUE base-second so received_at tie-breaks
        # deterministically. Allocate from the global pool.
        while True:
            s = rng.randrange(_WINDOW_SECONDS)
            if s not in used_seconds:
                used_seconds.add(s)
                break
        t_utc = _WINDOW_START + timedelta(seconds=s)
        ms = rng.randrange(1000)
        recv_str = _format_received_at(rng, t_utc, ms)
        rows.append(
            {
                "event_id": eid,
                "tenant_id": composite_key[0],
                "entity_id": composite_key[1],
                "event_kind": composite_key[2],
                "status": rng.choice(_STATUSES),
                "version": _format_version(rng, rng.randint(1, 12)),
                "received_at": recv_str,
                "supersedes_event_id": "",
                "source_node": sh,
            }
        )
    return eid, rows


def _make_all_logical_events(
    rng: random.Random,
) -> dict[tuple[str, str, str], list[dict]]:
    """Build a dict mapping composite_key → row replicas.

    A composite key has at most one logical event (one ``event_id``) by
    construction in this generator.
    """
    by_key: dict[tuple[str, str, str], list[dict]] = {}
    used_event_ids: set[str] = set()
    used_seconds: set[int] = set()
    keys: set[tuple[str, str, str]] = set()
    target_n = 220
    while len(keys) < target_n:
        keys.add(_pick_tenant_entity_kind(rng))
    for k in sorted(keys):
        _, rows = _make_logical_event(rng, used_event_ids, used_seconds, k)
        by_key[k] = rows
    return by_key


def _wire_supersedes(
    rng: random.Random,
    by_key: dict[tuple[str, str, str], list[dict]],
) -> set[str]:
    """For ~12% of logical events, point them at *another* logical event
    via ``supersedes_event_id``. Returns the set of superseded event_ids
    (used by the grader-side recompute as well).
    """
    keys = list(by_key.keys())
    rng.shuffle(keys)
    n_chains = max(1, int(0.12 * len(keys)))
    chosen = keys[:n_chains]
    superseded: set[str] = set()
    for k in chosen:
        # Pick a target logical event whose event_id we will point at, but
        # ensure it is a *different* composite key from k (the prompt says
        # the superseded event is removed entirely from the candidate
        # pool — including from its own composite key's group).
        target_k = rng.choice(keys)
        attempts = 0
        while target_k == k and attempts < 5:
            target_k = rng.choice(keys)
            attempts += 1
        if target_k == k:
            continue
        target_eid = by_key[target_k][0]["event_id"]
        # All replicas of k point at target_eid (consistent across shards).
        for r in by_key[k]:
            r["supersedes_event_id"] = target_eid
        superseded.add(target_eid)
    return superseded


def _write_shard_files(
    output_dir: Path,
    by_key: dict[tuple[str, str, str], list[dict]],
    rng: random.Random,
) -> None:
    cols = [
        "event_id",
        "tenant_id",
        "entity_id",
        "event_kind",
        "status",
        "version",
        "received_at",
        "supersedes_event_id",
        "source_node",
    ]
    by_shard: dict[str, list[dict]] = {s: [] for s in _SHARDS}
    for rows in by_key.values():
        for r in rows:
            r_emit = {k: r[k] for k in cols}
            by_shard[r["source_node"]].append(r_emit)
    for shard, rows in by_shard.items():
        rng.shuffle(rows)
        with open(output_dir / _FILES[shard], "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
            w.writeheader()
            for r in rows:
                w.writerow(r)


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    by_key = _make_all_logical_events(rng)
    _wire_supersedes(rng, by_key)
    _write_shard_files(output_dir, by_key, rng)


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
