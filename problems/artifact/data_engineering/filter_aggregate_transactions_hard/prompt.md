# Aggregate Non-Voided Transactions Across Four Regional Files

## Background

Four regional payment processors export their transaction logs to a central
data lake. Each region built its pipeline independently, so the four files
have substantially different schemas: column names, boolean representations,
date formats, and currencies all differ. Finance needs a single aggregated
table showing, per business sector, how many qualifying transactions occurred
in 2026 and their combined value in USD.

The workspace contains:

- `tx_na.csv` — North America, amounts in USD
- `tx_eu.csv` — Europe, amounts in EUR
- `tx_apac.csv` — Asia-Pacific, amounts in JPY
- `tx_latam.csv` — Latin America, amounts in BRL

## Source file schemas

### `tx_na.csv`

| Column | Type | Notes |
|---|---|---|
| `tx_id` | string | unique identifier, e.g. `NA-000001`. |
| `merchant_id` | string | merchant slug, e.g. `merch-042`. |
| `sector` | string | one of `finance`, `food`, `healthcare`, `retail`, `tech`. |
| `amount_usd` | string | transaction amount in USD, e.g. `149.99`. Plain decimal. |
| `tx_date` | string | date in **`YYYY-MM-DD`** format. |
| `voided` | string | `"true"` if the transaction was voided, `"false"` otherwise. |

### `tx_eu.csv`

| Column | Type | Notes |
|---|---|---|
| `id` | string | unique identifier, e.g. `EU-000001`. |
| `vendor_id` | string | merchant slug, same identifier space as NA. |
| `category` | string | same five values as `sector` in NA. |
| `amount_eur` | string | transaction amount in EUR. **About 25% of rows carry a leading `€` sign**, e.g. `€149.99`; the rest are plain decimals. |
| `date_eu` | string | date in **`DD/MM/YYYY`** format, e.g. `15/03/2026`. |
| `cancelled` | string | `"yes"` if cancelled, `"no"` otherwise. |

### `tx_apac.csv`

| Column | Type | Notes |
|---|---|---|
| `ref_no` | string | unique identifier, e.g. `APAC-000001`. |
| `merchant_code` | string | merchant slug, same identifier space. |
| `type` | string | same five sector values. |
| `amount_jpy` | string | transaction amount in JPY. Always a plain integer (no decimal point), e.g. `15000`. |
| `epoch_ms` | string | transaction date encoded as **epoch milliseconds** (13-digit integer), representing a UTC instant. Extract the calendar date in UTC to determine the year. |
| `rejected` | string | `"1"` if rejected, `"0"` otherwise. |

### `tx_latam.csv`

| Column | Type | Notes |
|---|---|---|
| `reference` | string | unique identifier, e.g. `LATAM-000001`. |
| `merch_id` | string | merchant slug, same identifier space. |
| `segment` | string | same five sector values. |
| `amount_brl` | string | transaction amount in BRL. **About 35% of rows carry a leading `R$` prefix**, e.g. `R$149.99`; the rest are plain decimals. May also have leading or trailing whitespace around the entire value. |
| `datetime_str` | string | date and time in **`YYYY-MM-DD HH:MM:SS`** format (UTC). Extract the calendar date to determine the year. |
| `blocked` | string | `"Y"` if blocked, `"N"` otherwise. |

## Currency conversion

All amounts must be converted to USD using these **fixed** exchange rates:

| Currency | Rate |
|---|---|
| EUR → USD | 1 EUR = 1.10 USD |
| JPY → USD | 150 JPY = 1 USD (i.e. divide JPY amount by 150) |
| BRL → USD | 5 BRL = 1 USD (i.e. divide BRL amount by 5) |

USD amounts need no conversion.

## Your task

Produce `output/sector_summary.csv` with **exactly these columns, in this
order**:

```
sector,tx_count,total_usd
```

Apply the following pipeline:

### Step 1 — Filter

Read all rows from **all four** files. Keep a row only when **all** of the
following conditions hold:

1. The transaction is **not** voided / cancelled / rejected / blocked
   (use the appropriate flag column per file).
2. The sector / category / type / segment is one of: `food`, `retail`,
   `tech`. Drop rows whose sector is `finance` or `healthcare`.
3. The transaction date falls in **calendar year 2026** — i.e. the year
   extracted from `tx_date`, `date_eu`, `epoch_ms`, or `datetime_str`
   (using the format rules above) equals 2026.
4. The USD-equivalent amount (after applying the exchange rate for the
   row's currency) is **≥ 10.00**.

Drop every row that fails any one of these four conditions.

### Step 2 — Aggregate

For the surviving rows, group by `sector` (the normalised sector value:
one of `food`, `retail`, `tech`) and compute:

- `tx_count` — count of surviving rows in that sector (across all four
  files combined).
- `total_usd` — sum of USD-equivalent amounts for those rows (apply the
  exchange rate per row before summing), formatted to **exactly 2 decimal
  places**.

All three sectors (`food`, `retail`, `tech`) MUST appear in the output,
even if a sector has zero qualifying transactions (`tx_count=0`,
`total_usd=0.00`).

### Row order (explicit)

Sort the output rows by `total_usd` **descending** (largest first).
For rows with equal `total_usd`, sort by `sector` **ascending** (A → Z)
as a tie-break.

### Output format

- Standard CSV with the header row exactly as above.
- UTF-8 encoded. Trailing newline at end of file.
- `total_usd` is formatted to exactly 2 decimal places.
