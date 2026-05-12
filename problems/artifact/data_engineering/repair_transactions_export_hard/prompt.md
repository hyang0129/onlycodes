# Repair the Treasury Transactions Export

## Background

The treasury team's nightly transactions export is built from a handful of
upstream systems that each have their own conventions.  Over the years the
formats have drifted and we now have a single CSV where most columns can
appear in several inconsistent forms.  Risk needs a clean, strictly-typed
version of this export to feed into the downstream reconciliation pipeline.

The workspace contains exactly one input file:

- `transactions_raw.csv` — the raw nightly export.

No other CSV files are present.

## Source file schema

| Column | Type | Notes |
|---|---|---|
| `tx_id` | string | unique identifier, e.g. `T-000001`. **Already clean.** |
| `account_id` | string | account code, e.g. `ACCT-017`. **Already clean.** |
| `amount` | string | transaction amount.  Many formats appear (see below).  The empty string represents a missing value — any row with a missing or unparseable amount must be **dropped**. |
| `tx_type` | string | transaction type, but written in any of several synonyms (see mapping). |
| `status` | string | transaction status, similarly inconsistent. |
| `is_disputed` | string | boolean in many forms — see boolean mapping. |
| `is_refunded` | string | boolean in many forms — same mapping as `is_disputed`. |
| `channel` | string | channel through which the transaction was made (web / mobile / branch / api), again with synonyms. |
| `notes` | string | free-text note.  Several upstream systems write different placeholder strings to indicate "no note" — these must all be collapsed to the empty string. |

## Repair rules

Apply the following rules to every input row, in order.  Any rule that
says **drop the row** terminates processing for that row.

### 1. `amount` — parse to a signed float (2 decimals)

Strip leading/trailing whitespace.  Then accept any of these forms (you may
see combinations of them on the same row):

| Form | Example | Parsed value |
|---|---|---|
| Plain decimal | `149.99` | `149.99` |
| Leading `$` | `$149.99` | `149.99` |
| Comma thousands separator | `1,234.56`, `$1,234.56` | `1234.56` |
| Trailing currency suffix | `149.99 USD`, `149.99USD` | `149.99` |
| Parentheses denote negative | `($1,234.56)`, `(1234.56)` | `-1234.56` |
| Literal `free` (case-insensitive) | `free`, `FREE` | `0.00` |

Specifically, the parsing procedure is:

1. Strip outer whitespace.
2. If the stripped value is the empty string, **drop the row**.
3. If the stripped value equals `free` (case-insensitive), the parsed
   amount is `0.0`.
4. Otherwise, check for surrounding parentheses; if present, strip them and
   set a `negative` flag.
5. Remove a leading `$` if present.
6. Remove a trailing ` USD` or `USD` (with or without a space) if present.
7. Remove any commas.
8. Strip whitespace again.
9. Attempt to parse the remainder as a float.  If parsing fails,
   **drop the row**.
10. If the `negative` flag was set, negate the result.

Output formatting: write the value with **exactly two decimal places**
(e.g. `149.99`, `-1234.56`, `0.00`).

### 2. `tx_type` — canonicalise, drop if unmapped

Apply this case-insensitive mapping (compare after stripping):

| Canonical | Accepted variants (case-insensitive) |
|---|---|
| `deposit` | `deposit`, `dep`, `depo`, `d` |
| `withdrawal` | `withdrawal`, `wd`, `with`, `w` |
| `transfer` | `transfer`, `xfer`, `trf`, `x` |
| `fee` | `fee`, `f` |

Anything else (including the empty string, `?`, `unknown`) → **drop the row**.

### 3. `status` — canonicalise, drop if unmapped

| Canonical | Accepted variants (case-insensitive) |
|---|---|
| `completed` | `completed`, `complete`, `done`, `ok` |
| `pending` | `pending`, `pend`, `in progress`, `wait` |
| `failed` | `failed`, `fail`, `err`, `error` |

Anything else → **drop the row**.

### 4. `is_disputed` and `is_refunded` — normalise to `true` / `false`

Apply this mapping (case-insensitive, after stripping):

| Output | Accepted inputs |
|---|---|
| `true` | `yes`, `y`, `true`, `1` |
| `false` | `no`, `n`, `false`, `0`, empty string |

Anything else → **drop the row**.

### 5. `channel` — canonicalise, drop if unmapped

| Canonical | Accepted variants (case-insensitive) |
|---|---|
| `web` | `web`, `www` |
| `mobile` | `mobile`, `mob`, `app`, `ios`, `android` |
| `branch` | `branch`, `br`, `in_person`, `in-person` |
| `api` | `api` |

Anything else → **drop the row**.

### 6. `notes` — strip null markers

After stripping leading/trailing whitespace, replace the value with the
empty string if it equals (case-insensitively) any of:

```
n/a, na, none, null, -, —, ?
```

Or if it is already the empty string.

Otherwise keep the **stripped** form (preserve interior text and case).

A note that becomes empty does **not** drop the row.

## Your task

Produce `output/transactions_clean.csv` with **exactly these columns, in
this order**:

```
tx_id,account_id,amount,tx_type,status,is_disputed,is_refunded,channel,notes
```

After applying the repair rules, write one row per surviving input row.

### Row order (explicit)

Sort the output by `tx_id` ascending (lexicographic).

### Output format

- Standard CSV with the header row exactly as above.
- UTF-8 encoded.  Trailing newline at end of file.
- `amount` is signed, with exactly 2 decimal places, no thousands
  separator, no currency symbol, no parentheses
  (e.g. `149.99`, `-1234.56`, `0.00`).
- `tx_type` ∈ `{deposit, withdrawal, transfer, fee}`.
- `status` ∈ `{completed, pending, failed}`.
- `is_disputed` and `is_refunded` ∈ `{true, false}`.
- `channel` ∈ `{web, mobile, branch, api}`.
- `notes` is a plain string (may be empty).  Do not quote unless the value
  contains a CSV special character; let the standard CSV writer handle
  quoting.
