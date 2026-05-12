"""Hidden grader for ``data_engineering__normalize_audit_log_dedup_hard``.

Recomputes the canonical audit table by walking all three shards in
``scratch_dir``, normalizing timestamps, dropping malformed rows,
deduplicating by ``(entity_id, action)``, and comparing the agent's
output row-for-row after canonical sort.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


OUTPUT_REL = "output/audit_canonical.csv"
EXPECTED_COLUMNS = [
    "entity_id",
    "action",
    "record_id",
    "source_shard",
    "recorded_at_utc",
]
SHARD_FILES = ["audit_alpha.csv", "audit_beta.csv", "audit_gamma.csv"]

_ISO_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_DIGITS_RE = re.compile(r"^\d+$")
_ISO_OFFSET_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}:\d{2}:\d{2})(?P<off>[+-]\d{2}:\d{2})$"
)
_NAIVE_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


def _parse_iso_z(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _parse_iso_offset(value: str) -> datetime:
    m = _ISO_OFFSET_RE.match(value)
    if not m:
        raise ValueError(value)
    sign = 1 if m["off"].startswith("+") else -1
    hh, mm = m["off"][1:].split(":")
    delta = timedelta(hours=int(hh), minutes=int(mm)) * sign
    local = datetime.strptime(m["date"] + "T" + m["time"], "%Y-%m-%dT%H:%M:%S")
    return (local - delta).replace(tzinfo=timezone.utc)


def _parse_epoch_ms(value: str) -> datetime:
    if len(value) != 13:
        raise ValueError(value)
    ms = int(value)
    return datetime.fromtimestamp(ms // 1000, tz=timezone.utc)


def _parse_naive_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _try_parse(raw: str) -> datetime | None:
    """Apply detection-then-strict-parse. Return None for malformed values."""
    value = raw.strip()
    if value == "":
        return None
    try:
        if _DIGITS_RE.match(value):
            return _parse_epoch_ms(value)
        if "T" in value and (value.endswith("Z") or re.search(r"[+-]\d\d:\d\d$", value)):
            if value.endswith("Z"):
                return _parse_iso_z(value)
            return _parse_iso_offset(value)
        if _NAIVE_RE.match(value):
            return _parse_naive_utc(value)
    except ValueError:
        return None
    return None


def _format_iso_z(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compute_expected(scratch_dir: Path) -> list[dict]:
    candidates: list[dict] = []
    for fname in SHARD_FILES:
        with open(scratch_dir / fname, newline="") as fh:
            for r in csv.DictReader(fh):
                ts = _try_parse(r["recorded_at"])
                if ts is None:
                    continue
                candidates.append(
                    {
                        "entity_id": r["entity_id"],
                        "action": r["action"],
                        "record_id": r["record_id"],
                        "source_shard": r["source_shard"],
                        "_ts_utc": ts,
                    }
                )

    by_key: dict[tuple[str, str], dict] = {}
    for c in candidates:
        key = (c["entity_id"], c["action"])
        cur = by_key.get(key)
        # Latest timestamp wins; tie → lexicographically smallest source_shard.
        # Build a sort key that's (ts_desc, shard_asc). Pick the row whose
        # (ts, -shard_rank) is max, i.e. compare (ts, -shard_rank_asc).
        if cur is None:
            by_key[key] = c
            continue
        cur_key = (cur["_ts_utc"], -ord(cur["source_shard"][0]))
        cand_key = (c["_ts_utc"], -ord(c["source_shard"][0]))
        if cand_key > cur_key:
            by_key[key] = c

    out = []
    for c in by_key.values():
        out.append(
            {
                "entity_id": c["entity_id"],
                "action": c["action"],
                "record_id": c["record_id"],
                "source_shard": c["source_shard"],
                "recorded_at_utc": _format_iso_z(c["_ts_utc"]),
            }
        )
    out.sort(key=lambda x: (x["entity_id"], x["action"]))
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
            f"row count mismatch: got {len(agent_rows)}, expected one canonical "
            f"row per (entity_id, action) after dropping malformed = {len(expected)}",
        )

    parsed: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()
    for i, row in enumerate(agent_rows, start=1):
        if len(row) != len(EXPECTED_COLUMNS):
            return GradeResult(
                False, 0.0, f"row {i} has {len(row)} fields, not {len(EXPECTED_COLUMNS)}"
            )
        entity_id, action, record_id, shard, ts_s = row
        if not _ISO_Z_RE.match(ts_s):
            return GradeResult(
                False,
                0.0,
                f"row {i}: recorded_at_utc {ts_s!r} must match YYYY-MM-DDTHH:MM:SSZ",
            )
        key = (entity_id, action)
        if key in seen_keys:
            return GradeResult(
                False,
                0.0,
                f"row {i}: composite key (entity_id, action)={key} appears more than once",
            )
        seen_keys.add(key)
        parsed.append(
            {
                "entity_id": entity_id,
                "action": action,
                "record_id": record_id,
                "source_shard": shard,
                "recorded_at_utc": ts_s,
            }
        )

    sort_key = lambda x: (x["entity_id"], x["action"])
    if [sort_key(r) for r in parsed] != [sort_key(r) for r in expected]:
        return GradeResult(
            False, 0.0, "rows not sorted by (entity_id asc, action asc) (or set differs)"
        )

    for i, (a, e) in enumerate(zip(parsed, expected), start=1):
        for k in EXPECTED_COLUMNS:
            if a[k] != e[k]:
                return GradeResult(
                    False,
                    0.0,
                    f"row {i}: {k} value disagrees with the expected dedup winner",
                )

    return GradeResult(
        True,
        1.0,
        f"normalized and deduplicated {len(expected)} (entity_id, action) keys "
        f"across three audit shards",
    )
