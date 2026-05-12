# Enrich Orders With Customer and Product Metadata

## Background

The orders system writes a thin transaction log. Customer and product details
live in separate reference tables. BI needs one wide table with everything
already joined so dashboards don't have to re-join on every query.

The workspace contains:

- `orders.csv` — the transaction log.
- `customers.csv` — customer reference table.
- `products.csv` — product reference table.

## Source file schemas

### `orders.csv`

| Column | Type | Notes |
|---|---|---|
| `order_id` | string | unique, e.g. `O-00001` |
| `cust_id` | integer | e.g. `42`. **Reference into customers**, but formatted as a plain integer (no leading zeros, no prefix). |
| `prod_code` | string | e.g. `P-012`. **Reference into products**, but uses a dash and zero-padding. |
| `order_date` | string | ISO 8601, `YYYY-MM-DD` |
| `quantity` | integer | ≥ 1 |
| `unit_price` | float | dollars, 2 decimal places |

### `customers.csv`

| Column | Type | Notes |
|---|---|---|
| `customer_id` | string | e.g. `C00042` — uppercase `C` followed by a **5-digit zero-padded** integer. The numeric part matches `orders.cust_id`. |
| `name` | string | full name |
| `email` | string | may be **empty** for some rows. Treat empty as missing-but-valid: keep the row, write an empty string in the output. |

### `products.csv`

| Column | Type | Notes |
|---|---|---|
| `sku` | string | e.g. `P12` — uppercase `P` followed by an **unpadded** integer, no dash. The numeric part matches `orders.prod_code`. |
| `product_name` | string | display name |
| `category` | string | one of `electronics`, `apparel`, `home`, `grocery`, `other` |

## Your task

Produce `output/enriched_orders.csv` with **exactly these columns, in this order**:

```
order_id,order_date,customer_name,customer_email,product_name,category,quantity,unit_price,line_total
```

For each row in `orders.csv`:

1. **Resolve the customer** by reconciling the ID format: `customers.customer_id == f"C{orders.cust_id:05d}"`.
2. **Resolve the product** by reconciling the ID format: `products.sku == f"P{int(orders.prod_code.removeprefix('P-')):d}"` — i.e. strip the `P-` prefix and any leading zeros, then prefix with `P`.
3. **If either the customer OR the product does not exist** in its lookup table, **drop that order row** (these are orphans — the reference is stale).
4. **If the customer email is empty**, keep the row and write an empty string for `customer_email`.
5. Compute `line_total = quantity × unit_price`, rounded to **2 decimal places**.

### Row order (explicit tie-break)

Sort the output by:

1. `order_date` ascending.
2. Within the same `order_date`, by `order_id` ascending (lexicographic).

### Output format

- Standard CSV with the header row exactly as above.
- `unit_price` and `line_total` formatted to **exactly 2 decimal places** (e.g. `49.99`).
- `quantity` is a plain integer (no decimal point).
- Empty `customer_email` is the empty string — **not** `null`, `None`, or `N/A`.
- UTF-8 encoded. Trailing newline at end of file.
