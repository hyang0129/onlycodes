# Aggregate Completed Sales Across Two Regional Files

## Background

Two regional warehouses export their daily sales logs to a shared bucket.
Each file has the same schema, but the raw `amount` column occasionally
carries leading or trailing whitespace that slipped through the export
pipeline. BI needs a per-category summary of only the orders that were
successfully completed.

The workspace contains:

- `sales_region_a.csv`
- `sales_region_b.csv`

## Source file schema (both files share this schema)

| Column | Type | Notes |
|---|---|---|
| `order_id` | string | unique within the file, e.g. `A-000123`. Always present. |
| `category` | string | product category; one of `clothing`, `electronics`, `food`, `home`, `sports`. Always present. |
| `amount` | string | sale amount in USD, e.g. `49.99`. Always a valid decimal number. **Some rows have leading and/or trailing whitespace** — strip before parsing. |
| `status` | string | one of `cancelled`, `completed`, `pending`, `refunded`. Always present, lowercase. |

## Your task

Produce `output/category_summary.csv` with **exactly these columns, in
this order**:

```
category,completed_orders,total_amount
```

Apply the following pipeline:

### Step 1 — Filter

Read all rows from **both** files. Keep only rows where `status` equals
`completed`. Drop every other row (regardless of whether the amount is
parseable or not).

### Step 2 — Aggregate

For the surviving rows, group by `category` and compute:

- `completed_orders` — count of surviving rows in that category (across
  both files combined).
- `total_amount` — sum of `amount` (after stripping whitespace and
  parsing as a decimal number) for those rows, formatted to **exactly
  2 decimal places** (e.g. `1234.56`, not `1234.560` or `1234.5`).

Every category that appears **anywhere** in the source files MUST appear in
the output, even if it has zero completed orders (`completed_orders=0`,
`total_amount=0.00`).

### Row order

Sort output rows by `category` ascending (lexicographic, A → Z).

### Output format

- Standard CSV with the header row exactly as above.
- UTF-8 encoded. Trailing newline at end of file.
- `total_amount` is formatted to exactly 2 decimal places.
