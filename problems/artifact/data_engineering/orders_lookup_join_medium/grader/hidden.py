"""Hidden grader for ``data_engineering__orders_lookup_join_medium``.

Recomputes the expected enriched join from ``orders.csv``,
``customers.csv``, and ``products.csv`` in ``scratch_dir`` and compares
the agent's output row-for-row after canonical sort.
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


OUTPUT_REL = "output/enriched_orders.csv"
EXPECTED_COLUMNS = [
    "order_id",
    "order_date",
    "customer_name",
    "customer_email",
    "product_name",
    "category",
    "quantity",
    "unit_price",
    "line_total",
]
AMOUNT_TOLERANCE = 0.01


def _product_key_from_prod_code(prod_code: str) -> str:
    """``P-007`` → ``P7``; ``P-12`` → ``P12``."""
    rest = prod_code.removeprefix("P-")
    return f"P{int(rest)}"


def _customer_key_from_cust_id(cust_id: str) -> str:
    """``42`` → ``C00042``."""
    return f"C{int(cust_id):05d}"


def _compute_expected(scratch_dir: Path) -> list[dict]:
    customers: dict[str, dict] = {}
    with open(scratch_dir / "customers.csv") as fh:
        for r in csv.DictReader(fh):
            customers[r["customer_id"]] = r

    products: dict[str, dict] = {}
    with open(scratch_dir / "products.csv") as fh:
        for r in csv.DictReader(fh):
            products[r["sku"]] = r

    out: list[dict] = []
    with open(scratch_dir / "orders.csv") as fh:
        for r in csv.DictReader(fh):
            ck = _customer_key_from_cust_id(r["cust_id"])
            pk = _product_key_from_prod_code(r["prod_code"])
            cust = customers.get(ck)
            prod = products.get(pk)
            if cust is None or prod is None:
                continue
            qty = int(r["quantity"])
            price = float(r["unit_price"])
            out.append(
                {
                    "order_id": r["order_id"],
                    "order_date": r["order_date"],
                    "customer_name": cust["name"],
                    "customer_email": cust["email"],
                    "product_name": prod["product_name"],
                    "category": prod["category"],
                    "quantity": qty,
                    "unit_price": price,
                    "line_total": round(qty * price, 2),
                }
            )

    out.sort(key=lambda x: (x["order_date"], x["order_id"]))
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
            f"row count mismatch: got {len(agent_rows)} (orphan rows must be dropped)",
        )

    parsed: list[dict] = []
    for i, row in enumerate(agent_rows, start=1):
        if len(row) != len(EXPECTED_COLUMNS):
            return GradeResult(
                False, 0.0, f"row {i} has {len(row)} fields, not {len(EXPECTED_COLUMNS)}"
            )
        oid, odate, cname, cemail, pname, cat, qty_s, price_s, lt_s = row

        try:
            datetime.strptime(odate, "%Y-%m-%d")
        except ValueError:
            return GradeResult(
                False, 0.0, f"row {i}: order_date {odate!r} is not ISO YYYY-MM-DD"
            )

        if not qty_s.isdigit():
            return GradeResult(
                False, 0.0, f"row {i}: quantity {qty_s!r} must be a plain integer"
            )

        for label, s in (("unit_price", price_s), ("line_total", lt_s)):
            if "." not in s or len(s.split(".")[-1]) != 2:
                return GradeResult(
                    False,
                    0.0,
                    f"row {i}: {label} {s!r} must have exactly 2 decimal places",
                )
            try:
                float(s)
            except ValueError:
                return GradeResult(False, 0.0, f"row {i}: {label} {s!r} is not numeric")

        parsed.append(
            {
                "order_id": oid,
                "order_date": odate,
                "customer_name": cname,
                "customer_email": cemail,
                "product_name": pname,
                "category": cat,
                "quantity": int(qty_s),
                "unit_price": float(price_s),
                "line_total": float(lt_s),
            }
        )

    sort_key = lambda x: (x["order_date"], x["order_id"])
    if [sort_key(r) for r in parsed] != [sort_key(r) for r in expected]:
        return GradeResult(
            False, 0.0, "rows not sorted by (order_date asc, order_id asc)"
        )

    for i, (a, e) in enumerate(zip(parsed, expected), start=1):
        for k in (
            "order_id",
            "order_date",
            "customer_name",
            "customer_email",
            "product_name",
            "category",
            "quantity",
        ):
            if a[k] != e[k]:
                return GradeResult(
                    False,
                    0.0,
                    f"row {i}: {k} value disagrees with the joined source data",
                )
        for k in ("unit_price", "line_total"):
            if abs(a[k] - e[k]) > AMOUNT_TOLERANCE:
                return GradeResult(
                    False, 0.0, f"row {i}: {k} off by more than ${AMOUNT_TOLERANCE:.2f}"
                )

    return GradeResult(
        True,
        1.0,
        f"joined and enriched {len(expected)} orders; orphans dropped, empty emails preserved",
    )
