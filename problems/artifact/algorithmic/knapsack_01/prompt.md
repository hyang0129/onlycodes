# Task: 0/1 Knapsack — Shipment Planning

Our logistics team has a single outbound pallet with a strict weight cap. They've
been handed a list of candidate parcels, each with a known weight and a known
shipping-revenue value. Each parcel is either sent on this pallet or held back —
it cannot be split, and we cannot send the same parcel twice.

**Find the subset of parcels that maximizes total revenue while keeping total
weight at or below the cap.**

## Input

Read `parcels.json` from your working directory:

```json
{
  "capacity": 160,
  "items": [
    {"id": 0, "weight": 23, "value": 92},
    {"id": 1, "weight": 31, "value": 57},
    ...
  ]
}
```

- `capacity`: integer weight cap (≤ 500).
- `items`: 30 items, each with `id` (0-indexed, distinct), `weight` (positive
  integer), and `value` (positive integer).

## Output

Write `output/pack.json`:

```json
{
  "total_value": <integer>,
  "chosen_ids": [<list of item ids included on the pallet>]
}
```

- `total_value`: sum of `value` of the chosen items. This must equal the global
  optimum.
- `chosen_ids`: (optional but validated if present) list of item ids selected.
  Duplicates not allowed; all ids must be valid; total weight must be ≤ `capacity`;
  the reported `total_value` must match the sum over chosen ids.

## Requirements

- The `total_value` must be **globally optimal** for 0/1 selection (each item
  used at most once).
- With N=30 items, a standard O(N × capacity) DP is the right tool. 2^30 brute
  force is NOT tractable.

## Verification

Run `python verify.py` to check your output has the correct shape before submitting.
