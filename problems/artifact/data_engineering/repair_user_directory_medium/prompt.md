# Repair the User Directory Export

## Background

The growth team exports a snapshot of the user directory once a week.  The
export job was written by three different people over the years and the
columns now contain a mix of conventions.  Marketing needs a clean version
for campaign targeting — every column normalised, malformed rows dropped,
and a single canonical representation per value.

The workspace contains exactly one input file:

- `user_directory_raw.csv` — the raw weekly export.

No other CSV files are present.

## Source file schema

| Column | Type | Notes |
|---|---|---|
| `user_id` | string | unique identifier, e.g. `U-000001`. **Already clean.** |
| `email` | string | user email, e.g. `jane@example.com`.  Case is inconsistent — the same address may appear as `Jane@Example.COM`.  Some rows have an empty string for this column. |
| `country` | string | free-form country label.  Many spellings are used for the same country (see mapping below).  Some rows contain a value that is not in the mapping (e.g. `Mars`, `Atlantis`, `?`). |
| `age` | string | mostly a non-negative integer, but: some rows contain word forms (`twenty`), the strings `unknown` / `N/A` / `null` / empty, or out-of-range integers (negative, `0`, `> 120`). |
| `is_active` | string | boolean in many forms: `yes`/`no`, `Y`/`N`, `true`/`false`, `TRUE`/`FALSE`, `1`/`0`, or empty.  No other values appear. |

## Repair rules

Apply the following rules to every input row, in order:

### 1. `email` — lowercase, drop if empty

- Strip leading/trailing whitespace.
- If the stripped value is the empty string, **drop the row**.
- Otherwise, normalise to **lowercase**.

### 2. `country` — canonicalise, drop if unmapped

Apply this case-insensitive mapping (compare after stripping whitespace and
lowercasing) to produce an ISO-2 country code:

| Canonical | Accepted variants (case-insensitive) |
|---|---|
| `US` | `us`, `usa`, `u.s.`, `u.s.a.`, `u.s.a`, `united states`, `united states of america`, `america` |
| `GB` | `gb`, `uk`, `u.k.`, `united kingdom`, `britain`, `great britain` |
| `FR` | `fr`, `france` |
| `DE` | `de`, `germany`, `deutschland` |
| `JP` | `jp`, `japan` |
| `CA` | `ca`, `canada` |

If the stripped/lowercased value does not match any variant above,
**drop the row**.

### 3. `age` — coerce or null

- Strip whitespace.
- If the value is empty, or equals (case-insensitively) any of
  `n/a`, `na`, `unknown`, `null`, `none`, `-`, or any word form
  (e.g. `twenty`), the age is **null** (output as the empty string).
- Otherwise, attempt to parse as an integer.  If the integer falls in the
  inclusive range **`[13, 120]`**, output that integer in plain decimal
  form (no leading zeros).
- Any integer outside `[13, 120]` (negative, `0`, `121`+) is also **null**
  (output as the empty string).

A `null` age does **not** cause the row to be dropped — only `email` and
`country` rules can drop rows.

### 4. `is_active` — normalise to `true` / `false`

Apply this mapping (case-insensitive after stripping whitespace):

| Output | Accepted inputs |
|---|---|
| `true` | `yes`, `y`, `true`, `1` |
| `false` | `no`, `n`, `false`, `0`, empty string |

No other inputs appear; assume the mapping is total.

## Your task

Produce `output/users_clean.csv` with **exactly these columns, in this
order**:

```
user_id,email,country,age,is_active
```

After applying the repair rules, write one row per surviving input row
(rows are dropped only by rules **1** and **2**).

### Row order (explicit)

Sort the output by `user_id` ascending (lexicographic).

### Output format

- Standard CSV with the header row exactly as above.
- UTF-8 encoded. Trailing newline at end of file.
- `age` is either a plain integer (no leading zeros) or the empty string.
- `is_active` is exactly `true` or `false`.
