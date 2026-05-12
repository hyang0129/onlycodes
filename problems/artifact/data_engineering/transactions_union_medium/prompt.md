# Union Three Quarterly Transaction Logs

## Background

The finance team has three quarterly transaction exports written by three
different systems. The schemas drifted significantly — each system encoded
amounts and currencies in its own way, and one of them has a free-form
`notes` column with commas in it. Your job is to union the three files
into one clean ledger.

The workspace contains:

- `tx_q1.csv`
- `tx_q2.csv`
- `tx_q3.csv`

## Source file schemas

### `tx_q1.csv`

| Column | Type | Notes |
|---|---|---|
| `tx_id` | string | unique, begins with `T1-`, e.g. `T1-0001` |
| `tx_date` | string | ISO 8601 `YYYY-MM-DD` |
| `amount` | float | always populated |
| `currency` | string | 3-letter ISO code but **case is inconsistent** (`USD`, `usd`, `Usd`) |

### `tx_q2.csv`

Wide-format: one column per currency. Per row, **exactly one** of the
three amount columns is populated; the other two are empty. If **all
three** are empty, the row has no amount and must be dropped.

| Column | Type | Notes |
|---|---|---|
| `tx_id` | string | unique, begins with `T2-` |
| `tx_date` | string | ISO 8601 |
| `amount_usd` | float or empty | populated → currency is `USD` |
| `amount_eur` | float or empty | populated → currency is `EUR` |
| `amount_gbp` | float or empty | populated → currency is `GBP` |

### `tx_q3.csv`

| Column | Type | Notes |
|---|---|---|
| `tx_id` | string | unique, begins with `T3-` |
| `tx_date` | string | ISO 8601 |
| `value` | string | a number, OR one of these null encodings: empty string, `NULL`, `N/A`, `—` (em-dash). Treat any of those as missing. |
| `ccy` | string | currency. May be a 3-letter code (`USD`, `EUR`, `GBP`) OR a full name (`US Dollar`, `Euro`, `British Pound`, `Pound Sterling`). Case may vary. May also be empty/missing. |
| `notes` | string | free-form text. **May contain commas, so this column is CSV-quoted.** Do not propagate `notes` to the output. |

## Currency normalization

The output currency code must be a 3-letter uppercase ISO 4217 code. The
following inputs are valid and map as follows (case-insensitive on the
left-hand side):

| Input (any case) | Output |
|---|---|
| `USD`, `US Dollar` | `USD` |
| `EUR`, `Euro` | `EUR` |
| `GBP`, `British Pound`, `Pound Sterling` | `GBP` |

Any other currency value (including missing/empty) means the row must be
dropped.

## Drop rules

Drop a row if **any** of the following is true:

1. The amount is missing (q2 with all three columns empty, q3 with `value`
   in `{"", "NULL", "N/A", "—"}`).
2. The amount cannot be parsed as a number.
3. The currency is missing or does not normalize to one of `USD`, `EUR`,
   `GBP`.

Otherwise the row is kept.

## Your task

Produce `output/transactions.csv` with **exactly these columns, in this order**:

```
tx_id,tx_date,amount_native,currency_code
```

Where:

- `tx_id` — verbatim from the source file.
- `tx_date` — verbatim ISO 8601 date.
- `amount_native` — numeric in the row's native currency, formatted to
  **exactly 2 decimal places** (e.g. `49.99`).
- `currency_code` — 3-letter uppercase ISO code: one of `USD`, `EUR`, `GBP`.

### Row order (explicit tie-break)

Sort by:

1. `tx_date` ascending.
2. Within the same `tx_date`, by `tx_id` ascending (lexicographic).

The `tx_id` prefixes (`T1-`, `T2-`, `T3-`) sort lexicographically, so
when dates tie, q1 rows come before q2 which come before q3.

### Output format

- Standard CSV with the header row exactly as above.
- UTF-8 encoded. Trailing newline at end of file.
- No `notes` column. No source-file column. Just the four columns.
