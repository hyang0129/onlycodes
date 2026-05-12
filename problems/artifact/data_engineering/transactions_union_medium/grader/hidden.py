"""Hidden grader for ``data_engineering__transactions_union_medium``."""

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


OUTPUT_REL = "output/transactions.csv"
EXPECTED_COLUMNS = ["tx_id", "tx_date", "amount_native", "currency_code"]
AMOUNT_TOLERANCE = 0.01

_CURRENCY_NORMALIZATION = {
    "usd": "USD",
    "us dollar": "USD",
    "eur": "EUR",
    "euro": "EUR",
    "gbp": "GBP",
    "british pound": "GBP",
    "pound sterling": "GBP",
}

_NULL_VALUE_FORMS = {"", "NULL", "N/A", "—"}


def _normalize_currency(raw: str) -> str | None:
    if raw is None:
        return None
    key = raw.strip().lower()
    return _CURRENCY_NORMALIZATION.get(key)


def _compute_expected(scratch_dir: Path) -> list[dict]:
    out: list[dict] = []

    with open(scratch_dir / "tx_q1.csv") as fh:
        for r in csv.DictReader(fh):
            cc = _normalize_currency(r["currency"])
            if cc is None:
                continue
            try:
                amt = float(r["amount"])
            except (ValueError, TypeError):
                continue
            out.append(
                {
                    "tx_id": r["tx_id"],
                    "tx_date": r["tx_date"],
                    "amount_native": amt,
                    "currency_code": cc,
                }
            )

    with open(scratch_dir / "tx_q2.csv") as fh:
        for r in csv.DictReader(fh):
            picked: tuple[str, str] | None = None
            for col, cc in (
                ("amount_usd", "USD"),
                ("amount_eur", "EUR"),
                ("amount_gbp", "GBP"),
            ):
                if r.get(col, ""):
                    picked = (r[col], cc)
                    break
            if picked is None:
                continue
            val_s, cc = picked
            try:
                amt = float(val_s)
            except (ValueError, TypeError):
                continue
            out.append(
                {
                    "tx_id": r["tx_id"],
                    "tx_date": r["tx_date"],
                    "amount_native": amt,
                    "currency_code": cc,
                }
            )

    with open(scratch_dir / "tx_q3.csv") as fh:
        for r in csv.DictReader(fh):
            cc = _normalize_currency(r["ccy"])
            if cc is None:
                continue
            v = r["value"]
            if v in _NULL_VALUE_FORMS:
                continue
            try:
                amt = float(v)
            except (ValueError, TypeError):
                continue
            out.append(
                {
                    "tx_id": r["tx_id"],
                    "tx_date": r["tx_date"],
                    "amount_native": amt,
                    "currency_code": cc,
                }
            )

    out.sort(key=lambda x: (x["tx_date"], x["tx_id"]))
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
            f"row count mismatch: got {len(agent_rows)} (drop rules must remove null amounts and unknown currencies)",
        )

    parsed: list[dict] = []
    for i, row in enumerate(agent_rows, start=1):
        if len(row) != len(EXPECTED_COLUMNS):
            return GradeResult(
                False, 0.0, f"row {i} has {len(row)} fields, not {len(EXPECTED_COLUMNS)}"
            )
        tx_id, tx_date, amt_s, cc = row
        try:
            datetime.strptime(tx_date, "%Y-%m-%d")
        except ValueError:
            return GradeResult(
                False, 0.0, f"row {i}: tx_date {tx_date!r} is not ISO YYYY-MM-DD"
            )
        if "." not in amt_s or len(amt_s.split(".")[-1]) != 2:
            return GradeResult(
                False,
                0.0,
                f"row {i}: amount_native {amt_s!r} must have exactly 2 decimal places",
            )
        try:
            amt = float(amt_s)
        except ValueError:
            return GradeResult(
                False, 0.0, f"row {i}: amount_native {amt_s!r} is not numeric"
            )
        if cc not in ("USD", "EUR", "GBP"):
            return GradeResult(
                False,
                0.0,
                f"row {i}: currency_code {cc!r} must be one of USD/EUR/GBP",
            )
        parsed.append(
            {
                "tx_id": tx_id,
                "tx_date": tx_date,
                "amount_native": amt,
                "currency_code": cc,
            }
        )

    sort_key = lambda x: (x["tx_date"], x["tx_id"])
    if [sort_key(r) for r in parsed] != [sort_key(r) for r in expectation]:
        return GradeResult(
            False, 0.0, "rows not sorted by (tx_date asc, tx_id asc)"
        )

    for i, (a, e) in enumerate(zip(parsed, expectation), start=1):
        for k in ("tx_id", "tx_date", "currency_code"):
            if a[k] != e[k]:
                return GradeResult(
                    False,
                    0.0,
                    f"row {i}: {k} value disagrees with the unioned source data",
                )
        if abs(a["amount_native"] - e["amount_native"]) > AMOUNT_TOLERANCE:
            return GradeResult(
                False,
                0.0,
                f"row {i}: amount_native off by more than ${AMOUNT_TOLERANCE:.2f}",
            )

    return GradeResult(
        True,
        1.0,
        f"unioned {len(expectation)} valid transactions across three schemas; null and unknown rows dropped",
    )
