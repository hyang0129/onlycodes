"""Public STRUCTURAL verifier for duplicate_orders.

Checks shape/schema ONLY — never correctness. Per SCHEMA §4, a trivially-wrong
artifact (e.g. empty or all fake pairs) may still pass verify(). Correctness
lives in grader/hidden.py.
"""

from __future__ import annotations

import json
from pathlib import Path

_REQUIRED_KEYS = {
    "order_id_a", "order_id_b", "customer_id", "sku",
    "amount_cents", "delta_seconds",
}


def verify(artifact_path: Path) -> None:
    artifact_path = Path(artifact_path)
    assert artifact_path.is_file(), f"artifact not found: {artifact_path}"

    raw = artifact_path.read_text()
    # Empty output is a shape-valid "no duplicates found" — let grader decide
    # correctness.
    if not raw.strip():
        return

    seen_pairs: set[tuple[str, str]] = set()
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"line {lineno}: not valid JSON ({exc.msg})"
            ) from None
        assert isinstance(row, dict), f"line {lineno}: row must be an object"

        keys = set(row.keys())
        missing = _REQUIRED_KEYS - keys
        extra = keys - _REQUIRED_KEYS
        assert not missing, f"line {lineno}: missing key(s) {sorted(missing)}"
        assert not extra, f"line {lineno}: unexpected key(s) {sorted(extra)}"

        a = row["order_id_a"]
        b = row["order_id_b"]
        assert isinstance(a, str) and a, f"line {lineno}: order_id_a must be non-empty string"
        assert isinstance(b, str) and b, f"line {lineno}: order_id_b must be non-empty string"
        assert a != b, f"line {lineno}: order_id_a == order_id_b (self-pair)"
        assert a < b, (
            f"line {lineno}: order_id_a must be < order_id_b lexicographically "
            f"(got {a!r}, {b!r})"
        )

        cid = row["customer_id"]
        sku = row["sku"]
        assert isinstance(cid, str) and cid, f"line {lineno}: customer_id must be non-empty string"
        assert isinstance(sku, str) and sku, f"line {lineno}: sku must be non-empty string"

        amt = row["amount_cents"]
        assert isinstance(amt, int) and not isinstance(amt, bool), (
            f"line {lineno}: amount_cents must be int"
        )
        assert amt >= 0, f"line {lineno}: amount_cents must be >= 0"

        delta = row["delta_seconds"]
        assert isinstance(delta, (int, float)) and not isinstance(delta, bool), (
            f"line {lineno}: delta_seconds must be a number"
        )
        assert 0.0 <= float(delta) <= 300.0 + 1e-6, (
            f"line {lineno}: delta_seconds {delta} outside [0, 300]"
        )

        pair = (a, b)
        assert pair not in seen_pairs, (
            f"line {lineno}: duplicate pair {pair} — each unordered pair must "
            "appear exactly once"
        )
        seen_pairs.add(pair)
