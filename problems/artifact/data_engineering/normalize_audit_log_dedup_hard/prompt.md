# Build a Canonical Audit Table Across Three Log Shards

## Background

The audit pipeline writes three parallel log shards — one per service
(`alpha`, `beta`, `gamma`). Every shard chose its own timestamp wire
format, and because the same logical action can be retried across
services, the shards overlap: the same `(entity_id, action)` pair often
appears in two or three shards. Downstream consumers want exactly **one
canonical row per `(entity_id, action)`**, with all timestamps
normalized to a single UTC form and malformed rows discarded.

The workspace contains exactly these three files:

- `audit_alpha.csv`
- `audit_beta.csv`
- `audit_gamma.csv`

## Source file schema (all three shards share this schema)

| Column | Type | Notes |
|---|---|---|
| `record_id` | string | unique within a shard, e.g. `rec-alpha-000123`. Across shards, IDs are disjoint by construction. |
| `entity_id` | string | the entity the action is about, e.g. `ent-00042`. Case-uniform. |
| `action` | string | one of `create`, `update`, `delete`, `archive`. |
| `recorded_at` | string | timestamp in one of the four formats below, or malformed. May have leading/trailing whitespace. |
| `source_shard` | string | exactly one of `alpha`, `beta`, `gamma`. Matches the file name. |

### `recorded_at` format rules

Strip leading and trailing whitespace before inspecting. After stripping,
the value is either malformed (see below) or matches exactly one of:

1. **ISO 8601 with explicit `Z` suffix**, e.g. `2026-04-01T14:23:00Z`.
   Already UTC. Second precision.

2. **ISO 8601 with explicit numeric offset**, e.g.
   `2026-04-01T14:23:00+05:30` or `2026-04-01T09:00:00-08:00`. Convert
   to UTC. Second precision. The offset is always `±HH:MM`.

3. **Epoch milliseconds** — a plain integer string of length exactly 13,
   e.g. `1743514025123`. Treat as a millisecond offset from the Unix
   epoch in UTC. Truncate sub-second toward whole seconds.

4. **Naive UTC**, `YYYY-MM-DD HH:MM:SS` (single space between date and
   time, no timezone marker). Treat as already-UTC.

Apply format detection per row, in this order, after stripping whitespace:

1. If the value is composed entirely of ASCII digits `0-9`, it is
   **epoch milliseconds** (format 3).
2. Else if the value contains a `T` **and** ends with either `Z` or a
   `±HH:MM` offset (i.e. the last 6 characters match `[+-]\d\d:\d\d` or
   the last character is `Z`), it is **ISO 8601** (formats 1 or 2).
3. Else if the value matches `YYYY-MM-DD HH:MM:SS` exactly (10 digits +
   dashes for the date, single space, 8 digits + colons for the time, no
   other characters), it is **naive UTC** (format 4).
4. Otherwise the row is **malformed** and must be dropped (see Step 1).

### Malformed-row examples

These shapes appear in the input and must all be dropped:

- empty string (after stripping),
- `not-a-time`,
- partial timestamps like `2026-13-01T00:00:00Z` (month out of range —
  the strict format check below will reject these via `strptime`),
- digit strings of the wrong length (e.g. 10 digits — epoch seconds, not
  milliseconds),
- garbage like `2026/04/01 14:00:00`.

You may detect malformed rows either by structural mismatch (failing the
shape checks above) or by `strptime` raising. Either way, drop the row.

## Your task

Produce `output/audit_canonical.csv` with **exactly these columns, in
this order**:

```
entity_id,action,record_id,source_shard,recorded_at_utc
```

Apply the following pipeline:

### Step 1 — Load and parse all shards

Concatenate rows from all three shards into a single conceptual table.
For each row:

- Strip whitespace from `recorded_at`.
- Apply format detection; if the row is **malformed** (does not match
  any of the four formats above, or fails strict parsing), **drop the
  row entirely** from the candidate pool.
- Otherwise, compute the row's UTC `datetime` (second precision).

### Step 2 — Group by composite key and pick a winner

Group surviving rows by `(entity_id, action)`. For each group, choose
**exactly one row** using this strict precedence ladder:

1. **Latest timestamp** — pick the row with the latest
   `recorded_at_utc` (post-normalization).
2. **Source shard** — among rows tied at timestamp, pick the row with
   the **lexicographically smallest** `source_shard` (so `alpha < beta
   < gamma`).
3. The data is generated so no further tie can occur — `record_id` is
   not needed as a third tie-break.

### Step 3 — Emit the canonical row

For each surviving group, emit exactly one row with:

- `entity_id`, `action`: the group key.
- `record_id`: the `record_id` of the winning row, copied through.
- `source_shard`: the winning row's shard, copied through.
- `recorded_at_utc`: the winning row's normalized timestamp, formatted
  as **`YYYY-MM-DDTHH:MM:SSZ`** — second precision, trailing `Z`, no
  fractional seconds, no numeric offset.

### Row order (explicit tie-break)

Sort the output by:

1. `entity_id` ascending (lexicographic).
2. Within the same `entity_id`, by `action` ascending (lexicographic).

`(entity_id, action)` is unique in the output, so this fully determines
row order.

### Output format

- Standard CSV with the header row exactly as above.
- `recorded_at_utc` is exactly `YYYY-MM-DDTHH:MM:SSZ`. No whitespace,
  no fractional seconds, always `Z` (never `+00:00`).
- UTF-8 encoded. Trailing newline at end of file.
