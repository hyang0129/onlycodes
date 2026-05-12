"""Hidden grader for ``data_engineering__customer_orders_join_easy``.

Recomputes the expected unified CSV from the two source files in
``scratch_dir`` and compares the agent's output row-for-row after
canonical sort.
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


OUTPUT_REL = "output/orders_unified.csv"
EXPECTED_COLUMNS = ["customer_id", "order_id", "order_date", "amount_usd", "source"]
AMOUNT_TOLERANCE = 0.01  # 2-decimal-place output → exact within a cent


def _parse_amount(raw: str) -> float:
    s = raw.strip()
    if s.startswith("$"):
        s = s[1:]
    return float(s)


def _compute_expected(scratch_dir: Path) -> list[dict]:
    rows: list[dict] = []

    north = scratch_dir / "orders_north.csv"
    with open(north) as fh:
        for r in csv.DictReader(fh):
            rows.append(
                {
                    "customer_id": r["customer_id"],
                    "order_id": r["order_id"],
                    "order_date": r["order_date"],  # already ISO
                    "amount_usd": _parse_amount(r["amount"]),
                    "source": "north",
                }
            )

    south = scratch_dir / "orders_south.csv"
    with open(south) as fh:
        for r in csv.DictReader(fh):
            mo, da, yr = r["date"].split("/")
            iso = f"{int(yr):04d}-{int(mo):02d}-{int(da):02d}"
            rows.append(
                {
                    "customer_id": r["cust_id"],
                    "order_id": r["order_id"],
                    "order_date": iso,
                    "amount_usd": _parse_amount(r["amount_str"]),
                    "source": "south",
                }
            )

    rows.sort(key=lambda x: (x["order_date"], x["order_id"]))
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
            f"row count mismatch: got {len(agent_rows)} rows (wrong total)",
        )

    # Validate each agent row's structure and parse amount.
    parsed: list[dict] = []
    for i, row in enumerate(agent_rows, start=1):
        if len(row) != len(EXPECTED_COLUMNS):
            return GradeResult(
                False,
                0.0,
                f"row {i} has {len(row)} fields, not {len(EXPECTED_COLUMNS)}",
            )
        cust, oid, odate, amt_s, src = row
        # Validate the date is ISO 8601.
        try:
            datetime.strptime(odate, "%Y-%m-%d")
        except ValueError:
            return GradeResult(
                False, 0.0, f"row {i}: order_date {odate!r} is not ISO YYYY-MM-DD"
            )
        # Validate amount is a plain number with 2 decimals.
        if "." not in amt_s or len(amt_s.split(".")[-1]) != 2:
            return GradeResult(
                False,
                0.0,
                f"row {i}: amount_usd {amt_s!r} must have exactly 2 decimal places",
            )
        try:
            amt = float(amt_s)
        except ValueError:
            return GradeResult(
                False, 0.0, f"row {i}: amount_usd {amt_s!r} is not numeric"
            )
        if src not in ("north", "south"):
            return GradeResult(
                False,
                0.0,
                f"row {i}: source {src!r} must be 'north' or 'south'",
            )
        parsed.append(
            {
                "customer_id": cust,
                "order_id": oid,
                "order_date": odate,
                "amount_usd": amt,
                "source": src,
            }
        )

    # Row order must match the canonical sort declared in the prompt.
    sort_key = lambda x: (x["order_date"], x["order_id"])
    if [sort_key(r) for r in parsed] != [sort_key(r) for r in expected]:
        return GradeResult(
            False,
            0.0,
            "rows not sorted by (order_date asc, order_id asc)",
        )

    # Cell-by-cell comparison after canonical order is confirmed.
    for i, (a, e) in enumerate(zip(parsed, expected), start=1):
        for k in ("customer_id", "order_id", "order_date", "source"):
            if a[k] != e[k]:
                return GradeResult(
                    False,
                    0.0,
                    f"row {i}: {k} value disagrees with the reconciled source data",
                )
        if abs(a["amount_usd"] - e["amount_usd"]) > AMOUNT_TOLERANCE:
            return GradeResult(
                False,
                0.0,
                f"row {i}: amount_usd off by more than ${AMOUNT_TOLERANCE:.2f}",
            )

    return GradeResult(
        True,
        1.0,
        f"unified {len(expected)} rows from two sources with reconciled schemas",
    )
