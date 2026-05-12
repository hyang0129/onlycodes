# Deduplicate the User Profile Export

## Background

The user-profile service writes a row to `users_raw.csv` every time a profile
is updated, but the export job runs hourly and re-emits any profile that has
been touched in the last 24 hours. As a result, the same user shows up
multiple times with slightly different versions of their data. BI wants the
**latest** profile per user, with the duplicates removed.

The workspace contains a single file:

- `users_raw.csv` — the raw export.

## Source file schema (`users_raw.csv`)

| Column | Type | Notes |
|---|---|---|
| `tenant` | string | tenant slug, e.g. `acme`, `globex`, `initech` |
| `user_id` | string | user identifier, unique **within a tenant**, e.g. `U-00012` |
| `name` | string | full display name |
| `email` | string | may be **empty** for some rows. Treat empty as missing-but-valid: keep the value (empty string) as-is. |
| `version` | integer | monotonically increasing per profile edit, ≥ 1 |
| `last_updated` | string | ISO 8601 in UTC, e.g. `2026-03-15T10:23:00Z`. Always present, always well-formed, always ends in `Z`. |

The same `(tenant, user_id)` pair can appear **1 or more times**. Different
tenants may share `user_id` values — those are different users.

## Your task

Produce `output/users_dedup.csv` with **exactly these columns, in this order**:

```
tenant,user_id,name,email,version,last_updated
```

Rules:

1. The composite key is **`(tenant, user_id)`**. Group rows by this key.
2. Within each group, keep **exactly one row** chosen as follows:
   1. The row with the **latest `last_updated`** wins.
   2. If two or more rows tie on `last_updated`, the row with the **highest `version`** wins.
   3. The source data is generated so no further tie can occur — you do not need to define a third tie-breaker.
3. Emit each surviving row exactly as it appeared in the input — do **not**
   recompute fields, do **not** trim whitespace, do **not** re-format
   `last_updated`. Just copy the cells of the winning row through.
4. Empty `email` stays the empty string — **not** `null`, `None`, or `N/A`.

### Row order (explicit tie-break)

Sort the output by:

1. `tenant` ascending (lexicographic).
2. Within the same `tenant`, by `user_id` ascending (lexicographic).

### Output format

- Standard CSV with the header row exactly as above.
- `version` is a plain integer (no decimal point).
- UTF-8 encoded. Trailing newline at end of file.
