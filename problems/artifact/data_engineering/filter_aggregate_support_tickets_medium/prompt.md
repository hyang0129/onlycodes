# Summarise High-Priority Resolved Support Tickets Across Three Regions

## Background

Three regional support teams each export their ticket logs independently.
They share the same conceptual data model — category, priority, resolution
status, and cost — but the schemas drifted over time: column names differ,
the resolved/closed flag is encoded three different ways, and one region's
cost column sometimes carries a leading `$` sign.

BI needs a single aggregated table counting resolved high-priority tickets
and their total cost, broken down by support category.

The workspace contains:

- `tickets_west.csv`
- `tickets_east.csv`
- `tickets_central.csv`

## Source file schemas

### `tickets_west.csv`

| Column | Type | Notes |
|---|---|---|
| `ticket_id` | string | unique identifier, e.g. `W-000042`. Always present. |
| `category` | string | one of `billing`, `hardware`, `network`, `security`, `software`. Always present. |
| `priority` | string | one of `critical`, `high`, `low`, `medium`. Always present, lowercase. |
| `resolved` | string | `"1"` if the ticket is resolved, `"0"` otherwise. |
| `cost_usd` | string | ticket handling cost in USD; a plain decimal, e.g. `45.00`. No currency symbol. Always a valid decimal; may have leading or trailing whitespace. |

### `tickets_east.csv`

| Column | Type | Notes |
|---|---|---|
| `ticket_id` | string | unique identifier, e.g. `E-000042`. Always present. |
| `category` | string | same five values as above. Always present. |
| `priority` | string | same four values as above. Always present, lowercase. |
| `is_resolved` | string | `"true"` if resolved, `"false"` otherwise (always lowercase). |
| `cost_usd` | string | same as `tickets_west.csv`. No currency symbol. May have whitespace. |

### `tickets_central.csv`

| Column | Type | Notes |
|---|---|---|
| `ticket_id` | string | unique identifier, e.g. `C-000042`. Always present. |
| `dept` | string | equivalent to `category` in the other files; same five values. Always present. |
| `priority` | string | same four values as above. Always present, lowercase. |
| `status` | string | `"closed"` if resolved, `"open"` if not. |
| `cost_usd` | string | a dollar amount. **About 30% of rows carry a leading `$`**, e.g. `$45.00`; the rest are plain decimals, e.g. `45.00`. May have leading or trailing whitespace around the entire value (including the `$`). |

## Your task

Produce `output/priority_resolved_summary.csv` with **exactly these
columns, in this order**:

```
category,ticket_count,total_cost
```

Apply the following pipeline:

### Step 1 — Filter

Read all rows from **all three** files. Keep a row only when **both**
conditions hold:

1. The ticket is resolved (`resolved == "1"`, or `is_resolved == "true"`,
   or `status == "closed"` — use the appropriate column per file).
2. The priority is `"high"` or `"critical"`.

Drop every row that fails either condition.

### Step 2 — Aggregate

For the surviving rows, group by `category` (using `dept` for
`tickets_central.csv`) and compute:

- `ticket_count` — count of surviving rows in that category (across all
  three files combined).
- `total_cost` — sum of `cost_usd` (strip whitespace and the leading `$`
  if present before parsing) for those rows, formatted to **exactly
  2 decimal places**.

Every category that appears **anywhere** in the source files MUST appear in
the output, even if it has zero qualifying tickets (`ticket_count=0`,
`total_cost=0.00`).

### Row order

Sort output rows by `category` ascending (lexicographic, A → Z).

### Output format

- Standard CSV with the header row exactly as above.
- UTF-8 encoded. Trailing newline at end of file.
- `total_cost` is formatted to exactly 2 decimal places.
