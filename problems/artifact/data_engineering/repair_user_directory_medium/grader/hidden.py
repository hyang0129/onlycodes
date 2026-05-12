"""Hidden grader for ``data_engineering__repair_user_directory_medium``.

Recomputes the expected repaired-user-directory output from
``user_directory_raw.csv`` and compares the agent's output row-for-row.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

EXPECTED_COLUMNS = ["user_id", "email", "country", "age", "is_active"]
OUTPUT_REL = "output/users_clean.csv"
INPUT_REL = "user_directory_raw.csv"

# Canonical country → set of accepted variants (compared after strip+lower).
_COUNTRY_MAP_RAW: dict[str, list[str]] = {
    "US": [
        "us", "usa", "u.s.", "u.s.a.", "u.s.a", "united states",
        "united states of america", "america",
    ],
    "GB": ["gb", "uk", "u.k.", "united kingdom", "britain", "great britain"],
    "FR": ["fr", "france"],
    "DE": ["de", "germany", "deutschland"],
    "JP": ["jp", "japan"],
    "CA": ["ca", "canada"],
}
_COUNTRY_LOOKUP: dict[str, str] = {
    v: canon for canon, variants in _COUNTRY_MAP_RAW.items() for v in variants
}

_BOOL_TRUE = {"yes", "y", "true", "1"}
_BOOL_FALSE = {"no", "n", "false", "0", ""}

_AGE_NULL_TOKENS = {"", "n/a", "na", "unknown", "null", "none", "-"}


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


def _normalise_email(raw: str) -> str | None:
    s = raw.strip()
    if s == "":
        return None
    return s.lower()


def _normalise_country(raw: str) -> str | None:
    s = raw.strip().lower()
    return _COUNTRY_LOOKUP.get(s)


def _normalise_age(raw: str) -> str:
    s = raw.strip()
    if s.lower() in _AGE_NULL_TOKENS:
        return ""
    try:
        v = int(s)
    except ValueError:
        return ""
    if 13 <= v <= 120:
        return str(v)
    return ""


def _normalise_bool(raw: str) -> str:
    s = raw.strip().lower()
    if s in _BOOL_TRUE:
        return "true"
    if s in _BOOL_FALSE:
        return "false"
    # Defensive: should not happen given generator, but treat unknown as drop.
    return "__UNMAPPED__"


def _compute_expected(scratch_dir: Path) -> list[list[str]]:
    out_rows: list[list[str]] = []
    with open(scratch_dir / INPUT_REL, newline="") as fh:
        for row in csv.DictReader(fh):
            email = _normalise_email(row["email"])
            if email is None:
                continue
            country = _normalise_country(row["country"])
            if country is None:
                continue
            age = _normalise_age(row["age"])
            is_active = _normalise_bool(row["is_active"])
            if is_active == "__UNMAPPED__":
                continue
            out_rows.append([row["user_id"], email, country, age, is_active])
    out_rows.sort(key=lambda r: r[0])
    return out_rows


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
            agent_rows = list(reader)
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
            f"row count mismatch: expected {len(expected)} rows, got {len(agent_rows)}",
        )

    for i, (row, exp) in enumerate(zip(agent_rows, expected), start=1):
        if len(row) != 5:
            return GradeResult(
                False, 0.0, f"row {i}: expected 5 fields, got {len(row)}"
            )
        if row != exp:
            return GradeResult(
                False,
                0.0,
                f"row {i}: agent={row} expected={exp}",
            )

    return GradeResult(
        True,
        1.0,
        f"all {len(expected)} repaired user rows match",
    )
