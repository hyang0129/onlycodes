"""Hidden grader for data_processing__duplicate_orders.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    The agent's output/duplicates.jsonl MUST contain exactly the set of
    unordered order-id pairs (order_id_a < order_id_b) satisfying:

      - same customer_id,
      - same sku,
      - same amount_cents,
      - abs(created_ts delta) <= 300.0,
      - distinct order_ids.

    Matching fields (customer_id, sku, amount_cents, delta_seconds) must also
    match; delta is checked with a small absolute tolerance.

Determinism: pure function of scratch_dir contents.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


INPUT_REL = "orders.jsonl"
OUTPUT_REL = "output/duplicates.jsonl"
WINDOW = 300.0
DELTA_ABS_TOL = 0.01

REQUIRED_KEYS = frozenset({
    "order_id_a", "order_id_b", "customer_id", "sku",
    "amount_cents", "delta_seconds",
})


def _compute_ground_truth(orders_path: Path) -> dict[tuple[str, str], dict]:
    """Return { (a,b): {customer_id, sku, amount_cents, delta_seconds} }
    where a < b lexicographically."""
    rows: list[dict] = []
    with open(orders_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))

    # Group by (customer, sku, amount)
    groups: dict[tuple[str, str, int], list[dict]] = {}
    for r in rows:
        key = (r["customer_id"], r["sku"], int(r["amount_cents"]))
        groups.setdefault(key, []).append(r)

    pairs: dict[tuple[str, str], dict] = {}
    for (cust, sku, amt), members in groups.items():
        if len(members) < 2:
            continue
        # Sort by ts so we can do an O(k^2) inner scan; k is small per group.
        members.sort(key=lambda r: float(r["created_ts"]))
        n = len(members)
        for i in range(n):
            for j in range(i + 1, n):
                a = members[i]
                b = members[j]
                delta = abs(float(a["created_ts"]) - float(b["created_ts"]))
                if delta > WINDOW:
                    # Members sorted by ts — once delta exceeds window, later
                    # j's can only be farther.
                    break
                a_id = a["order_id"]
                b_id = b["order_id"]
                if a_id == b_id:
                    continue
                low, high = (a_id, b_id) if a_id < b_id else (b_id, a_id)
                pairs[(low, high)] = {
                    "customer_id": cust,
                    "sku": sku,
                    "amount_cents": amt,
                    "delta_seconds": round(delta, 3),
                }
    return pairs


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    orders_path = scratch_dir / INPUT_REL
    output_path = scratch_dir / OUTPUT_REL

    if not orders_path.is_file():
        return GradeResult(False, 0.0, f"input {INPUT_REL} not found in scratch dir")
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    raw = output_path.read_text()

    truth = _compute_ground_truth(orders_path)

    agent_pairs: dict[tuple[str, str], dict] = {}
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            return GradeResult(
                False, 0.0,
                f"output line {lineno} failed to parse: {exc.msg}",
            )
        if not isinstance(row, dict):
            return GradeResult(False, 0.0, f"line {lineno}: row not an object")
        keys = set(row.keys())
        if keys != REQUIRED_KEYS:
            missing = REQUIRED_KEYS - keys
            extra = keys - REQUIRED_KEYS
            bits = []
            if missing:
                bits.append(f"missing {sorted(missing)}")
            if extra:
                bits.append(f"extra {sorted(extra)}")
            return GradeResult(False, 0.0, f"line {lineno}: {'; '.join(bits)}")

        a = row["order_id_a"]
        b = row["order_id_b"]
        if not isinstance(a, str) or not isinstance(b, str):
            return GradeResult(False, 0.0, f"line {lineno}: order_id must be string")
        if a >= b:
            return GradeResult(
                False, 0.0,
                f"line {lineno}: order_id_a must be < order_id_b (got {a!r}, {b!r})",
            )
        pair = (a, b)
        if pair in agent_pairs:
            return GradeResult(False, 0.0, f"line {lineno}: duplicate pair {pair}")
        agent_pairs[pair] = row

    truth_set = set(truth.keys())
    agent_set = set(agent_pairs.keys())

    missing_pairs = sorted(truth_set - agent_set)
    extra_pairs = sorted(agent_set - truth_set)
    if missing_pairs:
        return GradeResult(
            False, 0.0,
            f"missing {len(missing_pairs)} pair(s): {missing_pairs[:3]}"
            + (" ..." if len(missing_pairs) > 3 else ""),
        )
    if extra_pairs:
        return GradeResult(
            False, 0.0,
            f"{len(extra_pairs)} unexpected pair(s): {extra_pairs[:3]}"
            + (" ..." if len(extra_pairs) > 3 else ""),
        )

    # Field check for matched pairs.
    for pair, expected in truth.items():
        got = agent_pairs[pair]
        for k in ("customer_id", "sku"):
            if got[k] != expected[k]:
                return GradeResult(
                    False, 0.0,
                    f"pair {pair}: {k} mismatch (got {got[k]!r}, want {expected[k]!r})",
                )
        got_amt = got["amount_cents"]
        if isinstance(got_amt, bool) or not isinstance(got_amt, int):
            return GradeResult(False, 0.0, f"pair {pair}: amount_cents not int")
        if got_amt != expected["amount_cents"]:
            return GradeResult(
                False, 0.0,
                f"pair {pair}: amount_cents mismatch "
                f"(got {got_amt}, want {expected['amount_cents']})",
            )
        got_delta = got["delta_seconds"]
        if isinstance(got_delta, bool) or not isinstance(got_delta, (int, float)):
            return GradeResult(False, 0.0, f"pair {pair}: delta_seconds not number")
        if abs(float(got_delta) - expected["delta_seconds"]) > DELTA_ABS_TOL:
            return GradeResult(
                False, 0.0,
                f"pair {pair}: delta_seconds off "
                f"(got {got_delta}, want ~{expected['delta_seconds']})",
            )

    return GradeResult(
        True, 1.0,
        f"all {len(truth)} duplicate pair(s) matched",
    )
