# Multi-File Sales Cohort: Top Products by Revenue

## Background

You have 20 regional sales CSV files in the workspace, named `sales_region_01.csv` through `sales_region_20.csv`. Each file represents sales data from one geographic region.

## File Format

Each CSV file has the following columns:

| Column | Type | Description |
|--------|------|-------------|
| `product_id` | string | Product identifier (e.g. "P001", "P023") |
| `quantity` | integer | Number of units sold |
| `unit_price` | float | Price per unit in dollars |

## Your Task

1. Read all 20 CSV files from the workspace.
2. For each row, compute the **row revenue**: `quantity × unit_price`.
3. Sum the row revenues per `product_id` across **all 20 files** to get the **total revenue** for each product.
4. Identify the **top 5 products** by total revenue (highest first).
5. Write the results to `output/top_products.jsonl`.

## Output Format

Create the file `output/top_products.jsonl` (create the `output/` directory if needed).

The file must contain exactly **5 lines**, one JSON object per line, in **descending order by total_revenue**:

```
{"product_id": "P012", "total_revenue": 18234.50}
{"product_id": "P007", "total_revenue": 17891.23}
...
```

Requirements:
- Each line is a valid JSON object with keys `product_id` (string) and `total_revenue` (number).
- `total_revenue` must be rounded to **2 decimal places**.
- Lines must be in **descending order** by `total_revenue` (highest revenue first).
- The file must contain exactly **5 lines** (no blank lines, no header).
