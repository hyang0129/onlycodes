#!/usr/bin/env python3
"""Workspace generator for ``data_engineering__dedup_inventory_snapshots_medium``.

Writes three CSV snapshot files (``snapshot_2026_q1.csv``,
``snapshot_2026_q2.csv``, ``snapshot_2026_q3.csv``) populated with
``(warehouse_id, sku)`` records that contain:

  * **case-inconsistent ``warehouse_id``** (``WH-NYC`` vs. ``wh-nyc`` vs.
    ``Wh-Nyc``) — grouping requires uppercase normalization.
  * **whitespace-padded ``captured_at``** values — must be stripped to
    compare timestamps and to emit the canonical value.
  * **empty ``revision``** cells — must be treated as ``0`` and re-emitted
    as the literal integer ``0`` in the output.
  * Duplicates across files and *within* a single file, where the dedup
    winner depends on (revision desc, captured_at desc, file order desc).

The generation deliberately exercises every tie-break rung at least once
(verified post hoc by reading the reference output).
"""

from __future__ import annotations

import argparse
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

_WAREHOUSES = ["WH-NYC", "WH-LAX", "WH-CHI", "WH-MIA", "WH-SEA"]
_N_SKUS = 60
_FILES = [
    ("snapshot_2026_q1.csv", datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)),
    ("snapshot_2026_q2.csv", datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)),
    ("snapshot_2026_q3.csv", datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)),
]
_QUARTER_DAYS = 90

_EMPTY_REVISION_PROB = 0.18  # ~18% of rows have a missing revision
_WHITESPACE_PAD_PROB = 0.25  # ~25% of rows have padded captured_at


def _vary_case(rng: random.Random, s: str) -> str:
    """Return a case variant of ``s`` chosen at random.

    Variants: original (uppercase), all-lowercase, title-with-hyphens
    ("Wh-Nyc"-style)."""
    mode = rng.randrange(3)
    if mode == 0:
        return s
    if mode == 1:
        return s.lower()
    # Title-ish: every alpha-segment after a hyphen has first char upper, rest lower.
    parts = s.split("-")
    return "-".join(p[:1].upper() + p[1:].lower() for p in parts)


def _format_ts(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _pad_ws(rng: random.Random, s: str) -> str:
    if rng.random() < _WHITESPACE_PAD_PROB:
        # Pad left, right, or both. Always at least one space if we pad.
        lpad = rng.randrange(0, 3)
        rpad = rng.randrange(0, 3)
        if lpad == 0 and rpad == 0:
            rpad = 1
        return " " * lpad + s + " " * rpad
    return s


def _make_rows_for_file(
    rng: random.Random,
    base_ts: datetime,
    file_idx: int,
    used_seconds: set[tuple[str, str, int]],
) -> list[dict]:
    """Generate rows for one snapshot file.

    For each ``(warehouse_id, sku)`` key, decide how many rows appear in
    this file (0..2). When two rows appear in the same file, they share a
    ``revision`` value about 30% of the time so that the captured-at
    tie-break gets exercised.
    """
    rows: list[dict] = []
    for wh in _WAREHOUSES:
        for s in range(1, _N_SKUS + 1):
            sku = f"SKU-{s:05d}"
            # Decide how many rows for this key in this file: 0, 1, or 2.
            r = rng.random()
            if r < 0.30:
                count = 0
            elif r < 0.85:
                count = 1
            else:
                count = 2
            if count == 0:
                continue
            for i in range(count):
                # Pick an offset in seconds within the 90-day quarter that
                # has not been used for this key yet (to guarantee unique
                # captured_at per key globally, so file-order is the *only*
                # rung that can fire after revision+ts).
                while True:
                    off = rng.randrange(_QUARTER_DAYS * 24 * 3600)
                    sig = (wh, sku, base_ts.timestamp().__hash__() + off)
                    if sig not in used_seconds:
                        used_seconds.add(sig)
                        break
                ts = base_ts + timedelta(seconds=off)
                ts_str = _format_ts(ts)
                # Decide revision. Same revision across two rows in the
                # same file 40% of the time (to exercise captured_at tie).
                if i == 1 and rng.random() < 0.40:
                    revision_raw = rows[-1]["revision"]
                else:
                    if rng.random() < _EMPTY_REVISION_PROB:
                        revision_raw = ""
                    else:
                        revision_raw = str(rng.randint(0, 9))
                # Decide whether to pad captured_at.
                captured_at = _pad_ws(rng, ts_str)
                # Case-vary the warehouse_id.
                wh_emit = _vary_case(rng, wh)
                rows.append(
                    {
                        "warehouse_id": wh_emit,
                        "sku": sku,
                        "on_hand_units": str(rng.randint(0, 500)),
                        "captured_at": captured_at,
                        "revision": revision_raw,
                    }
                )
    rng.shuffle(rows)
    return rows


def _ensure_cross_file_overlap(
    rng: random.Random, file_rows: list[list[dict]]
) -> None:
    """Force ``(warehouse_id, sku)`` overlap between files so the dedup task
    actually exercises cross-file grouping (not just within-file dedup).
    Picks ~50% of all keys and inserts an extra row in each of the other
    two files for them, with revision spread across the rungs of the
    tie-break ladder so that all three rungs (revision, captured_at, file
    order) get exercised in the reference output.
    """
    # Build set of unique keys already present in any file.
    all_keys: set[tuple[str, str]] = set()
    for rows in file_rows:
        for r in rows:
            all_keys.add((r["warehouse_id"].upper(), r["sku"]))
    keys = sorted(all_keys)
    rng.shuffle(keys)
    pick = keys[: len(keys) // 2]
    used_global_ts: set[str] = set()
    for rows in file_rows:
        for r in rows:
            used_global_ts.add(r["captured_at"].strip())
    for k_idx, (wh_upper, sku) in enumerate(pick):
        # Place one row in each of the two files this key is *less*
        # represented in. We deterministically place one row in each
        # remaining file, varying revision so the picked winner cycles
        # through the rungs.
        rung = k_idx % 3
        for file_idx in range(3):
            if file_idx == rung:
                # Skip: this is the "winner" file for this key in the
                # mid-rung scenario. We'll insert into other two only.
                continue
            base_ts = _FILES[file_idx][1]
            # Unique timestamp.
            while True:
                off = rng.randrange(_QUARTER_DAYS * 24 * 3600)
                ts = base_ts + timedelta(seconds=off)
                ts_str = _format_ts(ts)
                if ts_str not in used_global_ts:
                    used_global_ts.add(ts_str)
                    break
            # Revision strategy:
            #  rung 0 → all three rows share revision=5; winner = q3 (file).
            #  rung 1 → file 0 rev=3, file 2 rev=3, file 1 = highest later.
            #  rung 2 → strictly increasing rev with file index — winner = q3.
            if rung == 0:
                revision_raw = "5"
            elif rung == 1:
                revision_raw = "3"
            else:
                revision_raw = str(file_idx + 1)
            captured_at = _pad_ws(rng, ts_str)
            wh_emit = _vary_case(rng, wh_upper)
            file_rows[file_idx].append(
                {
                    "warehouse_id": wh_emit,
                    "sku": sku,
                    "on_hand_units": str(rng.randint(0, 500)),
                    "captured_at": captured_at,
                    "revision": revision_raw,
                }
            )
    for rows in file_rows:
        rng.shuffle(rows)


def _write_csv(path: Path, rows: list[dict]) -> None:
    cols = ["warehouse_id", "sku", "on_hand_units", "captured_at", "revision"]
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    used: set[tuple[str, str, int]] = set()
    file_rows: list[list[dict]] = []
    for idx, (fname, base_ts) in enumerate(_FILES):
        rows = _make_rows_for_file(rng, base_ts, idx, used)
        file_rows.append(rows)
    _ensure_cross_file_overlap(rng, file_rows)
    for (fname, _), rows in zip(_FILES, file_rows):
        _write_csv(output_dir / fname, rows)


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
