# Unify Two Regional Order Logs

## Background

Two warehouses send order exports to a shared bucket. They were built by
different teams at different times, so the schemas drifted. Your job is to
read both files and produce a single, clean output that downstream BI can
consume without further cleaning.

The workspace contains:

- `orders_north.csv`
- `orders_south.csv`

## Source file schemas

### `orders_north.csv`

| Column | Type | Notes |
|---|---|---|
| `customer_id` | string | e.g. `C012` |
| `order_id` | string | begins with `N-`, e.g. `N-00001` |
| `order_date` | string | ISO 8601, `YYYY-MM-DD` |
| `amount` | string | a number in dollars, e.g. `49.99`. Some rows have leading or trailing whitespace around the number. |

### `orders_south.csv`

| Column | Type | Notes |
|---|---|---|
| `cust_id` | string | same identifier space as `customer_id` in the north file |
| `order_id` | string | begins with `S-`, e.g. `S-00001` |
| `date` | string | US format, `MM/DD/YYYY`, e.g. `01/15/2026` |
| `amount_str` | string | a dollar amount. **Most** rows are formatted as `$49.99`. **Some** rows are missing the `$` and look like `49.99`. Both forms refer to the same currency (USD). |

There are no missing or null values in either file. Every row in both files
must appear in your output.

## Your task

Write `output/orders_unified.csv` with **exactly these columns, in this order**:

```
customer_id,order_id,order_date,amount_usd,source
```

Rules:

- `customer_id` — the customer identifier (north's `customer_id` column or south's `cust_id` column).
- `order_id` — verbatim from the source file.
- `order_date` — ISO 8601 (`YYYY-MM-DD`). The south file's `MM/DD/YYYY` dates must be converted.
- `amount_usd` — numeric in dollars, formatted to **exactly 2 decimal places** (e.g. `49.99`, not `49.990` and not `49.9`). Strip whitespace and the leading `$` if present.
- `source` — the string `north` for rows from `orders_north.csv` and `south` for rows from `orders_south.csv`.

### Row order (tie-breaking is explicit)

Sort the output rows by:

1. `order_date` ascending (earliest first).
2. Within the same `order_date`, by `order_id` ascending (lexicographic).

Because `N-…` < `S-…` lexicographically, rows from the north file come
before rows from the south file when the dates tie.

### Output format

- Standard CSV with a header row matching the column list above.
- One row per input row across both files. The output must contain every
  row from both source files — no filtering, no deduplication.
- UTF-8 encoded. Trailing newline at end of file.
