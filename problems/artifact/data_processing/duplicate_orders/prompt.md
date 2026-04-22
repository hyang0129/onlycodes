# Duplicate Order Detection

Customer support flagged that our checkout is occasionally double-submitting
orders when users bounce on the confirm button. We need a quick report of
likely accidental duplicates so CX can refund proactively.

You are given an order log at `workspace/orders.jsonl` — one JSON object per
line. Each record has at least these fields:

- `order_id` — string, unique per row.
- `customer_id` — string.
- `sku` — string, the product code.
- `amount_cents` — int, order amount in cents (≥ 0).
- `created_ts` — float, seconds since epoch.
- `status` — string: `placed`, `cancelled`, or `refunded`.

## Task

Find **suspected duplicate order pairs** and write them to
`output/duplicates.jsonl`.

A pair of orders `(A, B)` is a suspected duplicate iff **all** of:

1. Same `customer_id`.
2. Same `sku`.
3. Same `amount_cents`.
4. Their `created_ts` values are within **300 seconds** of each other
   (`abs(A.created_ts - B.created_ts) <= 300.0`).
5. `A.order_id != B.order_id`.

Status is **not** part of the match criteria — a cancelled order and a placed
order with matching key still count as a duplicate pair.

Each unordered `{A, B}` pair must appear **exactly once** in the output. Emit
them as ordered pairs where `order_id_a < order_id_b` lexicographically. If a
customer/sku/amount cluster has more than two matching rows inside the window,
emit every unordered pair (i.e. for a 3-row cluster at times within window,
emit all 3 pairs).

## Output format

`output/duplicates.jsonl` — one JSON object per line, each with exactly these
keys:

```json
{"order_id_a": "<id>", "order_id_b": "<id>", "customer_id": "<id>", "sku": "<code>", "amount_cents": <int>, "delta_seconds": <float>}
```

- `order_id_a`, `order_id_b`: the two matched orders, with `order_id_a < order_id_b`.
- `customer_id`, `sku`, `amount_cents`: from the (identical) matched rows.
- `delta_seconds`: `abs(A.created_ts - B.created_ts)`, rounded to 3 decimals.
  The grader uses a small tolerance on this field.

Rows may be in any order. The grader checks the set of pairs.

## Optional public verifier

`workspace/verify.py` exposes `verify(artifact_path: Path)`; it checks shape
and key invariants (ordering, delta range, no self-pairs) but not correctness.

## Notes

- The log has ~5,000 rows; a naive O(n^2) scan is fine, but a
  group-then-window approach is cleaner.
- No network access is required or permitted.
- Extra keys in output rows will fail the grader.
