# Task: Reconcile Multi-Warehouse Inventory

Our WMS emits a stream of inventory transactions to `transactions.jsonl`.
Replay them and produce a per-warehouse / per-SKU final stock snapshot,
plus a list of rejected transactions.

Each transaction is a JSON object. Event types:

- `receive`
  ```json
  {"id": "T00001", "type": "receive", "warehouse": "WH1", "sku": "SKU-A", "qty": 10}
  ```
  Adds `qty` to `(warehouse, sku)`.

- `ship`
  ```json
  {"id": "T00002", "type": "ship", "warehouse": "WH1", "sku": "SKU-A", "qty": 3}
  ```
  Subtracts `qty` from `(warehouse, sku)`. **Reject** the transaction (do not
  mutate stock) if the resulting quantity would be negative.

- `transfer`
  ```json
  {"id": "T00003", "type": "transfer", "from": "WH1", "to": "WH2",
   "sku": "SKU-A", "qty": 5}
  ```
  Atomically moves `qty` from `(from, sku)` to `(to, sku)`. **Reject** if
  `(from, sku)` does not have enough stock (do not mutate either side).

- `adjust`
  ```json
  {"id": "T00004", "type": "adjust", "warehouse": "WH1", "sku": "SKU-A",
   "delta": -2}
  ```
  Applies signed `delta` to `(warehouse, sku)`. **Reject** if the result
  would be negative.

A `(warehouse, sku)` pair starts at `0` the first time it is referenced.

## Output

Write `output/reconciliation.json`:

```json
{
  "stock": {
    "WH1": {"SKU-A": 7, "SKU-B": 0},
    "WH2": {"SKU-A": 5}
  },
  "rejected": [
    {"id": "T00042", "reason": "insufficient_stock"},
    {"id": "T00099", "reason": "insufficient_stock"}
  ],
  "totals": {
    "accepted": 987,
    "rejected": 13
  }
}
```

Rules for the output:

- `stock` — nested object. Include every `(warehouse, sku)` pair that was
  ever referenced, even if the final balance is `0`. Integer values only.
- `rejected` — list of objects in the same order the transactions appear
  in the input stream. `reason` is always the string
  `"insufficient_stock"`. Include every rejected transaction.
- `totals.accepted` + `totals.rejected` must sum to the total number of
  events in the input.
