"""Hidden grader for ``data_engineering__events_cross_region_join_hard``."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


OUTPUT_REL = "output/events.csv"
EXPECTED_COLUMNS = [
    "event_utc_ts",
    "user_id",
    "user_tier",
    "event_type",
    "source_region",
]
VALID_EVENT_TYPES = {"page_view", "add_to_cart", "checkout", "login", "logout"}
VALID_REGIONS = {"us", "eu", "apac"}
VALID_TIERS = {"free", "pro", "enterprise"}

_TOKYO = timezone(timedelta(hours=9))
_CAMEL_SPLIT = re.compile(r"(?<=[a-z])(?=[A-Z])")


def _normalize_event_type(raw: str) -> str | None:
    """Apply: insert ``_`` between lowercase→uppercase boundaries, replace
    spaces with ``_``, lowercase, then validate against the closed set."""
    if raw is None:
        return None
    s = _CAMEL_SPLIT.sub("_", raw)
    s = s.replace(" ", "_")
    s = s.lower()
    return s if s in VALID_EVENT_TYPES else None


def _us_to_utc(epoch_s: int) -> datetime:
    return datetime.fromtimestamp(int(epoch_s), tz=timezone.utc)


def _eu_to_utc(iso_with_tz: str) -> datetime:
    # ``datetime.fromisoformat`` in Python 3.11 handles ``+HH:MM`` offsets.
    return datetime.fromisoformat(iso_with_tz).astimezone(timezone.utc)


def _apac_to_utc(naive_iso: str) -> datetime:
    naive = datetime.fromisoformat(naive_iso)
    return naive.replace(tzinfo=_TOKYO).astimezone(timezone.utc)


def _fmt_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_users(scratch_dir: Path) -> dict[int, str]:
    users: dict[int, str] = {}
    with open(scratch_dir / "users.csv") as fh:
        for r in csv.DictReader(fh):
            users[int(r["user_id"])] = r["tier"]
    return users


def _iter_jsonl(path: Path):
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _compute_expected(scratch_dir: Path) -> list[dict]:
    users = _load_users(scratch_dir)
    out: list[dict] = []

    for r in _iter_jsonl(scratch_dir / "events_us.jsonl"):
        evt = _normalize_event_type(r.get("evt", ""))
        if evt is None:
            continue
        uid = int(r["uid"])
        if uid not in users:
            continue
        out.append(
            {
                "event_utc_ts": _fmt_utc(_us_to_utc(r["ts"])),
                "user_id": uid,
                "user_tier": users[uid],
                "event_type": evt,
                "source_region": "us",
            }
        )

    for r in _iter_jsonl(scratch_dir / "events_eu.jsonl"):
        evt = _normalize_event_type(r.get("event", ""))
        if evt is None:
            continue
        raw_uid = r["userId"]
        uid = int(raw_uid.removeprefix("u-"))
        if uid not in users:
            continue
        out.append(
            {
                "event_utc_ts": _fmt_utc(_eu_to_utc(r["timestamp"])),
                "user_id": uid,
                "user_tier": users[uid],
                "event_type": evt,
                "source_region": "eu",
            }
        )

    for r in _iter_jsonl(scratch_dir / "events_apac.jsonl"):
        evt = _normalize_event_type(r.get("action", ""))
        if evt is None:
            continue
        raw_uid = r["user_id"]
        uid = int(raw_uid.removeprefix("USER_"))
        if uid not in users:
            continue
        out.append(
            {
                "event_utc_ts": _fmt_utc(_apac_to_utc(r["time_local"])),
                "user_id": uid,
                "user_tier": users[uid],
                "event_type": evt,
                "source_region": "apac",
            }
        )

    out.sort(key=lambda x: (x["event_utc_ts"], x["user_id"], x["source_region"]))
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

    expectation = _compute_expected(scratch_dir)

    if len(agent_rows) != len(expectation):
        return GradeResult(
            False,
            0.0,
            f"row count mismatch: got {len(agent_rows)} (orphans + unknown event types must be dropped)",
        )

    parsed: list[dict] = []
    iso_re = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    for i, row in enumerate(agent_rows, start=1):
        if len(row) != len(EXPECTED_COLUMNS):
            return GradeResult(
                False, 0.0, f"row {i} has {len(row)} fields, not {len(EXPECTED_COLUMNS)}"
            )
        ts, uid_s, tier, evt, region = row
        if not iso_re.match(ts):
            return GradeResult(
                False, 0.0, f"row {i}: event_utc_ts {ts!r} must be YYYY-MM-DDTHH:MM:SSZ"
            )
        if not uid_s.isdigit():
            return GradeResult(
                False, 0.0, f"row {i}: user_id {uid_s!r} must be a plain integer"
            )
        if tier not in VALID_TIERS:
            return GradeResult(
                False, 0.0, f"row {i}: user_tier {tier!r} must be one of {sorted(VALID_TIERS)}"
            )
        if evt not in VALID_EVENT_TYPES:
            return GradeResult(
                False, 0.0, f"row {i}: event_type {evt!r} must be one of {sorted(VALID_EVENT_TYPES)}"
            )
        if region not in VALID_REGIONS:
            return GradeResult(
                False, 0.0, f"row {i}: source_region {region!r} must be one of {sorted(VALID_REGIONS)}"
            )
        parsed.append(
            {
                "event_utc_ts": ts,
                "user_id": int(uid_s),
                "user_tier": tier,
                "event_type": evt,
                "source_region": region,
            }
        )

    sort_key = lambda x: (x["event_utc_ts"], x["user_id"], x["source_region"])
    if [sort_key(r) for r in parsed] != [sort_key(r) for r in expectation]:
        return GradeResult(
            False,
            0.0,
            "rows not sorted by (event_utc_ts asc, user_id asc, source_region asc)",
        )

    for i, (a, e) in enumerate(zip(parsed, expectation), start=1):
        for k in EXPECTED_COLUMNS:
            if a[k] != e[k]:
                return GradeResult(
                    False,
                    0.0,
                    f"row {i}: {k} value disagrees with the joined and normalized source data",
                )

    return GradeResult(
        True,
        1.0,
        f"unioned {len(expectation)} valid events across three regions with timezone and user-tier joins",
    )
