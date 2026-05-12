"""Hidden grader for ``data_engineering__filter_aggregate_transactions_hard``.

Recomputes the expected per-sector summary from all four source files and
compares the agent's output row-for-row.

Filtering rules:
  - not voided / cancelled / rejected / blocked
  - sector in {food, retail, tech}
  - calendar year of transaction date == 2026
  - USD-equivalent amount >= 10.00

Currency rates:
  - EUR × 1.10 → USD
  - JPY ÷ 150  → USD
  - BRL ÷ 5    → USD
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

EXPECTED_COLUMNS = ["sector", "tx_count", "total_usd"]
OUTPUT_REL = "output/sector_summary.csv"

_KEEP_SECTORS = {"food", "retail", "tech"}
_EUR_TO_USD = 1.10
_JPY_TO_USD = 1 / 150
_BRL_TO_USD = 1 / 5
_MIN_USD = 10.00


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


def _parse_amount_eur(raw: str) -> float:
    s = raw.strip()
    if s.startswith("€"):
        s = s[1:]
    return float(s) * _EUR_TO_USD


def _parse_amount_brl(raw: str) -> float:
    s = raw.strip()
    if s.startswith("R$"):
        s = s[2:]
    return float(s) * _BRL_TO_USD


def _year_from_iso(date_str: str) -> int:
    return int(date_str[:4])


def _year_from_dmy(date_str: str) -> int:
    # DD/MM/YYYY
    parts = date_str.strip().split("/")
    return int(parts[2])


def _year_from_epoch_ms(epoch_ms_str: str) -> int:
    ms = int(epoch_ms_str.strip())
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.year


def _year_from_datetime_str(dt_str: str) -> int:
    # YYYY-MM-DD HH:MM:SS
    return int(dt_str.strip()[:4])


def _compute_expected(scratch_dir: Path) -> list[dict]:
    counts: dict[str, int] = {s: 0 for s in _KEEP_SECTORS}
    totals: dict[str, float] = {s: 0.0 for s in _KEEP_SECTORS}

    # NA: USD, YYYY-MM-DD, voided "true"/"false"
    with open(scratch_dir / "tx_na.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["voided"] == "true":
                continue
            sector = row["sector"]
            if sector not in _KEEP_SECTORS:
                continue
            if _year_from_iso(row["tx_date"]) != 2026:
                continue
            usd = float(row["amount_usd"])
            if usd < _MIN_USD:
                continue
            counts[sector] += 1
            totals[sector] += usd

    # EU: EUR (€ prefix on ~25%), DD/MM/YYYY, cancelled "yes"/"no"
    with open(scratch_dir / "tx_eu.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["cancelled"] == "yes":
                continue
            sector = row["category"]
            if sector not in _KEEP_SECTORS:
                continue
            if _year_from_dmy(row["date_eu"]) != 2026:
                continue
            usd = _parse_amount_eur(row["amount_eur"])
            if usd < _MIN_USD:
                continue
            counts[sector] += 1
            totals[sector] += usd

    # APAC: JPY integer, epoch_ms, rejected "1"/"0"
    with open(scratch_dir / "tx_apac.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["rejected"] == "1":
                continue
            sector = row["type"]
            if sector not in _KEEP_SECTORS:
                continue
            if _year_from_epoch_ms(row["epoch_ms"]) != 2026:
                continue
            usd = int(row["amount_jpy"]) * _JPY_TO_USD
            if usd < _MIN_USD:
                continue
            counts[sector] += 1
            totals[sector] += usd

    # LATAM: BRL (R$ prefix on ~35%), YYYY-MM-DD HH:MM:SS, blocked "Y"/"N"
    with open(scratch_dir / "tx_latam.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["blocked"] == "Y":
                continue
            sector = row["segment"]
            if sector not in _KEEP_SECTORS:
                continue
            if _year_from_datetime_str(row["datetime_str"]) != 2026:
                continue
            usd = _parse_amount_brl(row["amount_brl"])
            if usd < _MIN_USD:
                continue
            counts[sector] += 1
            totals[sector] += usd

    rows = [
        {
            "sector": s,
            "tx_count": counts[s],
            "total_usd": f"{totals[s]:.2f}",
        }
        for s in _KEEP_SECTORS
    ]
    # Sort by total_usd DESC, then sector ASC
    rows.sort(key=lambda r: (-float(r["total_usd"]), r["sector"]))
    return rows


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
            f"row count mismatch: got {len(agent_rows)} rows (one per sector is correct)",
        )

    for i, (row, exp) in enumerate(zip(agent_rows, expected), start=1):
        if len(row) != 3:
            return GradeResult(
                False, 0.0, f"row {i} has {len(row)} fields, expected 3"
            )
        sector, count_s, total_s = row

        if sector != exp["sector"]:
            return GradeResult(
                False,
                0.0,
                f"row {i}: sector {sector!r} is out of sort order",
            )

        try:
            count = int(count_s)
        except ValueError:
            return GradeResult(
                False, 0.0, f"row {i}: tx_count {count_s!r} is not an integer"
            )

        if count != exp["tx_count"]:
            return GradeResult(
                False,
                0.0,
                f"row {i} ({sector}): tx_count disagrees with expected value",
            )

        try:
            total = float(total_s)
        except ValueError:
            return GradeResult(
                False, 0.0, f"row {i}: total_usd {total_s!r} is not numeric"
            )

        exp_total = float(exp["total_usd"])
        if abs(total - exp_total) > 0.005:
            return GradeResult(
                False,
                0.0,
                f"row {i} ({sector}): total_usd disagrees with expected value",
            )

        if "." not in total_s or len(total_s.split(".")[-1]) != 2:
            return GradeResult(
                False,
                0.0,
                f"row {i}: total_usd {total_s!r} must have exactly 2 decimal places",
            )

    return GradeResult(
        True,
        1.0,
        f"all {len(expected)} sector rows match (multi-file, multi-currency filter+aggregate)",
    )
