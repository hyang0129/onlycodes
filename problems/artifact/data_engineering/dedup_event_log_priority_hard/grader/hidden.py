"""Hidden grader for ``data_engineering__dedup_event_log_priority_hard``.

Recomputes the canonical event table from the three audit-log shards in
``scratch_dir`` and compares the agent's output row-for-row after the
canonical sort by ``(tenant_id, entity_id, event_kind)``.

The recomputation pipeline mirrors the prompt:

  1. Load all rows; auto-detect ``received_at`` format and normalize to
     a UTC ``datetime``; strip the ``v`` prefix from ``version``.
  2. Build the supersedes set (any ``event_id`` referenced by another
     row's ``supersedes_event_id``); drop those rows entirely.
  3. Group surviving rows by ``(tenant_id, entity_id, event_kind)``;
     pick the winner using the precedence ladder
     status > version > received_at > source_node.
  4. Emit canonical rows.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


OUTPUT_REL = "output/events_canonical.csv"
EXPECTED_COLUMNS = [
    "tenant_id",
    "entity_id",
    "event_kind",
    "event_id",
    "status",
    "version",
    "received_at_utc",
]
SOURCE_FILES = ["events_alpha.csv", "events_beta.csv", "events_gamma.csv"]

# Higher number = higher precedence.
STATUS_PRECEDENCE = {
    "COMMITTED": 4,
    "RETRIED": 3,
    "PENDING": 2,
    "FAILED": 1,
}
_VALID_STATUS = set(STATUS_PRECEDENCE)
_VALID_KIND = {"created", "updated", "deleted", "archived"}
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
_EPOCH_MS_RE = re.compile(r"^\d{13}$")
_ISO_OFFSET_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})$"
)
_NAIVE_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}$")


def _parse_received_at(raw: str) -> datetime:
    """Auto-detect format and return a UTC-aware datetime with microsecond precision."""
    s = raw
    if _EPOCH_MS_RE.match(s):
        ms = int(s)
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).replace(
            microsecond=(ms % 1000) * 1000
        )
    if _ISO_OFFSET_RE.match(s):
        s2 = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s2).astimezone(timezone.utc)
    if _NAIVE_RE.match(s):
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S.%f").replace(
            tzinfo=timezone.utc
        )
    raise ValueError(f"unrecognized received_at format: {raw!r}")


def _parse_version(raw: str) -> int:
    s = raw.strip()
    if s.startswith("v"):
        s = s[1:]
    return int(s)


def _format_canonical_ts(t: datetime) -> str:
    if t.tzinfo is not None:
        t = t.astimezone(timezone.utc).replace(tzinfo=None)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond:06d}Z"


def _compute_expected(scratch_dir: Path) -> list[dict]:
    all_rows: list[dict] = []
    for fname in SOURCE_FILES:
        with open(scratch_dir / fname, newline="") as fh:
            for r in csv.DictReader(fh):
                received_utc = _parse_received_at(r["received_at"])
                version_int = _parse_version(r["version"])
                all_rows.append(
                    {
                        "event_id": r["event_id"],
                        "tenant_id": r["tenant_id"],
                        "entity_id": r["entity_id"],
                        "event_kind": r["event_kind"],
                        "status": r["status"],
                        "version": version_int,
                        "received_at_utc": received_utc,
                        "supersedes_event_id": r.get("supersedes_event_id", ""),
                        "source_node": r["source_node"],
                    }
                )

    superseded: set[str] = set()
    for r in all_rows:
        sup = r["supersedes_event_id"]
        if sup:
            superseded.add(sup)

    candidates = [r for r in all_rows if r["event_id"] not in superseded]

    def _better(a: dict, b: dict) -> dict:
        """Return whichever of ``a`` and ``b`` wins the precedence ladder."""
        for getter in (
            lambda x: STATUS_PRECEDENCE[x["status"]],
            lambda x: x["version"],
            lambda x: x["received_at_utc"],
        ):
            ga, gb = getter(a), getter(b)
            if ga != gb:
                return a if ga > gb else b
        # Final rung: lexicographically *smallest* source_node wins.
        if a["source_node"] != b["source_node"]:
            return a if a["source_node"] < b["source_node"] else b
        return a  # full tie — generator promises this never happens

    by_key: dict[tuple[str, str, str], dict] = {}
    for r in candidates:
        key = (r["tenant_id"], r["entity_id"], r["event_kind"])
        cur = by_key.get(key)
        by_key[key] = r if cur is None else _better(cur, r)

    out = []
    for v in by_key.values():
        out.append(
            {
                "tenant_id": v["tenant_id"],
                "entity_id": v["entity_id"],
                "event_kind": v["event_kind"],
                "event_id": v["event_id"],
                "status": v["status"],
                "version": v["version"],
                "received_at_utc": _format_canonical_ts(v["received_at_utc"]),
            }
        )
    out.sort(key=lambda x: (x["tenant_id"], x["entity_id"], x["event_kind"]))
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
            f"(tenant_id, entity_id, event_kind) composite key after dropping "
            f"superseded events = {len(expected)}",
        )

    parsed: list[dict] = []
    for i, row in enumerate(agent_rows, start=1):
        if len(row) != len(EXPECTED_COLUMNS):
            return GradeResult(
                False,
                0.0,
                f"row {i} has {len(row)} fields, not {len(EXPECTED_COLUMNS)}",
            )
        tenant, entity, kind, eid, status, version_s, ts_s = row
        if kind not in _VALID_KIND:
            return GradeResult(
                False,
                0.0,
                f"row {i}: event_kind {kind!r} must be one of {sorted(_VALID_KIND)}",
            )
        if status not in _VALID_STATUS:
            return GradeResult(
                False,
                0.0,
                f"row {i}: status {status!r} must be one of {sorted(_VALID_STATUS)}",
            )
        if not version_s.isdigit():
            return GradeResult(
                False,
                0.0,
                f"row {i}: version {version_s!r} must be a plain integer (no 'v' prefix)",
            )
        if not _TS_RE.match(ts_s):
            return GradeResult(
                False,
                0.0,
                f"row {i}: received_at_utc {ts_s!r} must match "
                "YYYY-MM-DDTHH:MM:SS.ffffffZ",
            )
        parsed.append(
            {
                "tenant_id": tenant,
                "entity_id": entity,
                "event_kind": kind,
                "event_id": eid,
                "status": status,
                "version": int(version_s),
                "received_at_utc": ts_s,
            }
        )

    sort_key = lambda x: (x["tenant_id"], x["entity_id"], x["event_kind"])
    if [sort_key(r) for r in parsed] != [sort_key(r) for r in expected]:
        return GradeResult(
            False,
            0.0,
            "rows not sorted by (tenant_id asc, entity_id asc, event_kind asc)",
        )

    for i, (a, e) in enumerate(zip(parsed, expected), start=1):
        for k in (
            "tenant_id",
            "entity_id",
            "event_kind",
            "event_id",
            "status",
            "version",
            "received_at_utc",
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
        f"deduplicated {len(expected)} (tenant_id, entity_id, event_kind) "
        f"composite keys after applying status precedence and dropping superseded events",
    )
