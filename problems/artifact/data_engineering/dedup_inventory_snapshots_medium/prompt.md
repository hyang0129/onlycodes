# Build the Current Inventory From Three Quarterly Snapshots

## Background

Each quarter, every warehouse uploads a CSV snapshot of its on-hand inventory.
Snapshots are not authoritative individually — a SKU may have been recounted
mid-quarter, so the "current" on-hand value is whichever recount has the
highest `revision` number. Operations needs a single deduplicated table
showing the current state of every `(warehouse_id, sku)` pair.

The workspace contains three snapshot files:

- `snapshot_2026_q1.csv`
- `snapshot_2026_q2.csv`
- `snapshot_2026_q3.csv`

These three filenames are guaranteed; **no other CSV files** appear in the
workspace.

## Source file schema (all three snapshots share this schema)

| Column | Type | Notes |
|---|---|---|
| `warehouse_id` | string | warehouse code, e.g. `WH-NYC`. **The case is inconsistent across files** — the same warehouse may appear as `wh-nyc`, `WH-NYC`, or `Wh-Nyc`. Normalize to **uppercase** for both grouping and output. |
| `sku` | string | product SKU, case-sensitive, e.g. `SKU-00042`. Already uniform. |
| `on_hand_units` | integer | non-negative count |
| `captured_at` | string | ISO 8601 datetime in UTC, e.g. `2026-02-14T08:30:00Z`. **Some values have leading or trailing whitespace** — strip before comparing. After stripping, the value is always well-formed. |
| `revision` | string | integer ≥ 0, **but may be the empty string** for snapshots taken before the recount system was deployed. **Treat empty as `0`.** |

The same `(warehouse_id, sku)` pair (after case normalization) can appear
**0 or more times** within a single snapshot file and may appear in any
combination of the three files.

## Your task

Produce `output/inventory_current.csv` with **exactly these columns, in this order**:

```
warehouse_id,sku,on_hand_units,captured_at,revision
```

Rules:

1. The composite key is **`(warehouse_id_normalized, sku)`** where
   `warehouse_id_normalized = warehouse_id.upper()`. Group rows by this key.
2. Within each group, keep **exactly one row** chosen as follows:
   1. The row with the **highest `revision`** (treating empty as `0`) wins.
   2. If two or more rows tie on `revision`, the row with the **latest
      `captured_at`** (after whitespace stripping) wins.
   3. If two or more rows tie on both, the row from the **file whose name
      sorts last lexicographically** wins. (i.e. `snapshot_2026_q3.csv` >
      `snapshot_2026_q2.csv` > `snapshot_2026_q1.csv`.)
   4. The source data is generated so no further tie can occur.
3. Output the chosen row with the following normalizations applied:
   - `warehouse_id`: **uppercase** form.
   - `sku`: as-is.
   - `on_hand_units`: as-is (plain integer).
   - `captured_at`: **whitespace-stripped** form.
   - `revision`: integer in plain form (so an originally-empty `revision`
     becomes `0`; a row that originally had `revision = "07"` becomes `7`).

### Row order (explicit tie-break)

Sort the output by:

1. `warehouse_id` (uppercase form) ascending (lexicographic).
2. Within the same `warehouse_id`, by `sku` ascending (lexicographic).

### Output format

- Standard CSV with the header row exactly as above.
- `on_hand_units` and `revision` are plain integers (no decimal point).
- UTF-8 encoded. Trailing newline at end of file.
