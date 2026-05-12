"""Hidden grader for ``data_engineering__dedup_inventory_snapshots_medium``.

Recomputes the deduplicated inventory from the three snapshot files in
``scratch_dir`` and compares the agent's output row-for-row after the
canonical sort by ``(warehouse_id, sku)`` (warehouse_id uppercased).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


OUTPUT_REL = "output/inventory_current.csv"
EXPECTED_COLUMNS = [
    "warehouse_id",
    "sku",
    "on_hand_units",
    "captured_at",
    "revision",
]
SOURCE_FILES = [
    "snapshot_2026_q1.csv",
    "snapshot_2026_q2.csv",
    "snapshot_2026_q3.csv",
]


def _parse_revision(raw: str) -> int:
    s = raw.strip()
    if s == "":
        return 0
    return int(s)


def _compute_expected(scratch_dir: Path) -> list[dict]:
    by_key: dict[tuple[str, str], dict] = {}
    for file_idx, fname in enumerate(SOURCE_FILES):
        with open(scratch_dir / fname, newline="") as fh:
            for r in csv.DictReader(fh):
                wh_norm = r["warehouse_id"].upper()
                sku = r["sku"]
                key = (wh_norm, sku)
                ts_clean = r["captured_at"].strip()
                rev = _parse_revision(r["revision"])
                cand = {
                    "warehouse_id": wh_norm,
                    "sku": sku,
                    "on_hand_units": int(r["on_hand_units"]),
                    "captured_at": ts_clean,
                    "revision": rev,
                    "_file_idx": file_idx,
                }
                cur = by_key.get(key)
                if cur is None:
                    by_key[key] = cand
                    continue
                # Tie-break ladder: revision desc, captured_at desc,
                # file_idx desc (later file wins).
                cur_t = (cur["revision"], cur["captured_at"], cur["_file_idx"])
                cand_t = (cand["revision"], cand["captured_at"], cand["_file_idx"])
                if cand_t > cur_t:
                    by_key[key] = cand

    out = []
    for v in by_key.values():
        # Drop the helper field before returning.
        out.append(
            {
                "warehouse_id": v["warehouse_id"],
                "sku": v["sku"],
                "on_hand_units": v["on_hand_units"],
                "captured_at": v["captured_at"],
                "revision": v["revision"],
            }
        )
    out.sort(key=lambda x: (x["warehouse_id"], x["sku"]))
    return out


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    output_path = scratch_dir / OUTPUT_REL

    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        with open(output_path, newline="") as fh:
            reader = csv.reader(fh)
            try:
                header = next(reader)
            except StopIteration:
                return GradeResult(False, 0.0, "output artifact is empty")
            agent_rows = [row for row in reader]
    except Exception as exc:
        return GradeResult(False, 0.0, f"could not parse output: {exc}")

    if header != EXPECTED_COLUMNS:
        return GradeResult(
            False,
            0.0,
            f"column header must be exactly {EXPECTED_COLUMNS} in that order; got {header}",
        )

    expected = _compute_expected(scratch_dir)

    if len(agent_rows) != len(expected):
        return GradeResult(
            False,
            0.0,
            f"row count mismatch: got {len(agent_rows)}, expected one row per "
            f"(warehouse_id, sku) composite key (uppercased) = {len(expected)}",
        )

    parsed: list[dict] = []
    for i, row in enumerate(agent_rows, start=1):
        if len(row) != len(EXPECTED_COLUMNS):
            return GradeResult(
                False,
                0.0,
                f"row {i} has {len(row)} fields, not {len(EXPECTED_COLUMNS)}",
            )
        wh, sku, units_s, ts_s, rev_s = row
        if wh != wh.upper():
            return GradeResult(
                False, 0.0, f"row {i}: warehouse_id {wh!r} must be uppercased"
            )
        if not units_s.isdigit():
            return GradeResult(
                False,
                0.0,
                f"row {i}: on_hand_units {units_s!r} must be a non-negative integer",
            )
        if not rev_s.isdigit():
            return GradeResult(
                False,
                0.0,
                f"row {i}: revision {rev_s!r} must be a non-negative integer "
                "(empty must be normalized to 0)",
            )
        try:
            datetime.strptime(ts_s, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return GradeResult(
                False,
                0.0,
                f"row {i}: captured_at {ts_s!r} must match YYYY-MM-DDTHH:MM:SSZ "
                "(strip whitespace before emitting)",
            )
        parsed.append(
            {
                "warehouse_id": wh,
                "sku": sku,
                "on_hand_units": int(units_s),
                "captured_at": ts_s,
                "revision": int(rev_s),
            }
        )

    sort_key = lambda x: (x["warehouse_id"], x["sku"])
    if [sort_key(r) for r in parsed] != [sort_key(r) for r in expected]:
        return GradeResult(
            False, 0.0, "rows not sorted by (warehouse_id asc, sku asc)"
        )

    for i, (a, e) in enumerate(zip(parsed, expected), start=1):
        for k in (
            "warehouse_id",
            "sku",
            "on_hand_units",
            "captured_at",
            "revision",
        ):
            if a[k] != e[k]:
                return GradeResult(
                    False,
                    0.0,
                    f"row {i}: {k} value disagrees with the expected dedup winner",
                )

    return GradeResult(
        True,
        1.0,
        f"deduplicated {len(expected)} (warehouse_id, sku) keys across "
        f"{len(SOURCE_FILES)} snapshot files",
    )
