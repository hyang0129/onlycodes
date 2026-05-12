"""Hidden grader for ``data_engineering__dedup_user_profiles_easy``.

Recomputes the expected deduplication of ``users_raw.csv`` in
``scratch_dir`` and compares the agent's output row-for-row after canonical
sort by ``(tenant, user_id)``.
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


OUTPUT_REL = "output/users_dedup.csv"
EXPECTED_COLUMNS = [
    "tenant",
    "user_id",
    "name",
    "email",
    "version",
    "last_updated",
]


def _compute_expected(scratch_dir: Path) -> list[dict]:
    by_key: dict[tuple[str, str], dict] = {}
    with open(scratch_dir / "users_raw.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            key = (r["tenant"], r["user_id"])
            cur = by_key.get(key)
            cand = {
                "tenant": r["tenant"],
                "user_id": r["user_id"],
                "name": r["name"],
                "email": r["email"],
                "version": int(r["version"]),
                "last_updated": r["last_updated"],
            }
            if cur is None:
                by_key[key] = cand
                continue
            # latest last_updated wins; tie → highest version.
            cur_key = (cur["last_updated"], cur["version"])
            cand_key = (cand["last_updated"], cand["version"])
            if cand_key > cur_key:
                by_key[key] = cand

    out = list(by_key.values())
    out.sort(key=lambda x: (x["tenant"], x["user_id"]))
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
            f"(tenant, user_id) composite key = {len(expected)}",
        )

    parsed: list[dict] = []
    for i, row in enumerate(agent_rows, start=1):
        if len(row) != len(EXPECTED_COLUMNS):
            return GradeResult(
                False,
                0.0,
                f"row {i} has {len(row)} fields, not {len(EXPECTED_COLUMNS)}",
            )
        tenant, user_id, name, email, version_s, ts_s = row
        if not version_s.isdigit():
            return GradeResult(
                False, 0.0, f"row {i}: version {version_s!r} must be a plain integer"
            )
        try:
            datetime.strptime(ts_s, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return GradeResult(
                False,
                0.0,
                f"row {i}: last_updated {ts_s!r} must match YYYY-MM-DDTHH:MM:SSZ",
            )
        parsed.append(
            {
                "tenant": tenant,
                "user_id": user_id,
                "name": name,
                "email": email,
                "version": int(version_s),
                "last_updated": ts_s,
            }
        )

    sort_key = lambda x: (x["tenant"], x["user_id"])
    if [sort_key(r) for r in parsed] != [sort_key(r) for r in expected]:
        return GradeResult(
            False, 0.0, "rows not sorted by (tenant asc, user_id asc)"
        )

    for i, (a, e) in enumerate(zip(parsed, expected), start=1):
        for k in ("tenant", "user_id", "name", "email", "version", "last_updated"):
            if a[k] != e[k]:
                return GradeResult(
                    False,
                    0.0,
                    f"row {i}: {k} value disagrees with the expected dedup winner",
                )

    return GradeResult(
        True,
        1.0,
        f"deduplicated {len(expected)} (tenant, user_id) keys, latest-wins resolved",
    )
