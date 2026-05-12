# Build a Canonical Event Table From Three Audit Log Shards

## Background

The audit pipeline writes three parallel log shards (`events_alpha.csv`,
`events_beta.csv`, `events_gamma.csv`) — one per ingestion node. The shards
overlap heavily: the same logical event can appear in 1, 2, or all 3 shards
because retries replay across nodes. Downstream consumers want **exactly one
row per logical event**, with the row chosen by an explicit precedence
ladder, and timestamps normalized to a single canonical UTC format.

The workspace contains exactly these three files:

- `events_alpha.csv`
- `events_beta.csv`
- `events_gamma.csv`

## Source file schema (all three shards share this schema)

| Column | Type | Notes |
|---|---|---|
| `event_id` | string | globally unique event identifier, e.g. `evt-9f3a1c`. Same logical event re-ingested by two shards keeps the same `event_id`. |
| `tenant_id` | string | tenant slug, e.g. `acme`. Already case-uniform. |
| `entity_id` | string | the entity the event is about, e.g. `order-12345`. Already case-uniform. |
| `event_kind` | string | one of `created`, `updated`, `deleted`, `archived`. |
| `status` | string | one of `COMMITTED`, `RETRIED`, `PENDING`, `FAILED`. |
| `version` | string | integer ≥ 1, **but may be prefixed with the literal letter `v`** (e.g. `v3` → version 3). Strip the prefix if present. |
| `received_at` | string | timestamp in **one of three formats** (mixed across rows): |
| | | • ISO 8601 with timezone offset, e.g. `2026-05-12T14:23:00+02:00` |
| | | • Epoch milliseconds as a plain integer string, e.g. `1747044180123` |
| | | • Naive UTC, `YYYY-MM-DD HH:MM:SS.fff` (always millisecond precision; no timezone marker), e.g. `2026-05-12 12:23:00.123` |
| `supersedes_event_id` | string | `event_id` of the event this one logically replaces. Empty when the event does not supersede anything. |
| `source_node` | string | shard name (`alpha`, `beta`, or `gamma`). |

## Logical event identity

The composite key for a logical event is **`(tenant_id, entity_id, event_kind)`** — i.e. there is at most one canonical event per `(tenant, entity, kind)` triple in the output.

## Your task

Produce `output/events_canonical.csv` with **exactly these columns, in this order**:

```
tenant_id,entity_id,event_kind,event_id,status,version,received_at_utc
```

Apply the following pipeline:

### Step 1 — Load and normalize all rows from all three shards

Treat the three shards as a single conceptual table. For each row:

- Strip the `v` prefix from `version` if present; the value is then a
  positive integer.
- Normalize `received_at` to a UTC `datetime` using the format detection
  rules above. **Auto-detect the format per row**:
  - if the value parses as a base-10 integer of length 13, treat it as
    epoch milliseconds (UTC);
  - else if it contains a `T` and ends with either `Z` or a `±HH:MM`
    offset, parse as ISO 8601 with offset and convert to UTC;
  - else parse as `YYYY-MM-DD HH:MM:SS.fff` and treat it as already-UTC.

### Step 2 — Drop superseded rows

Build the set of all `event_id` values that appear in **any** row's
`supersedes_event_id` column (across all three shards, after dropping empty
values). Any row whose own `event_id` is in this set is **dropped entirely**
from the candidate pool — it has been superseded by a later event and must
not appear in the canonical output, no matter how high its precedence
would otherwise be.

### Step 3 — Group by composite key and pick a winner

Group the surviving rows by `(tenant_id, entity_id, event_kind)`. For each
group, choose **exactly one row** using this strict precedence ladder:

1. **Status precedence** — pick the row with the highest-precedence
   `status`, where the order is

   ```
   COMMITTED > RETRIED > PENDING > FAILED
   ```

2. **Version** — among rows tied at status, pick the highest `version`.
3. **Received-at** — among rows tied at version, pick the **latest**
   `received_at_utc` (post-normalization).
4. **Source node** — among rows still tied, pick the row with the
   **lexicographically smallest** `source_node` (i.e. `alpha < beta <
   gamma`).
5. The data is generated so no further tie can occur.

### Step 4 — Emit the canonical row

For each surviving group, emit exactly one row with:

- `tenant_id`, `entity_id`, `event_kind`: the group key.
- `event_id`: the `event_id` of the winning row.
- `status`: the winning row's status, **as-is** (one of the four uppercase
  values listed above).
- `version`: the winning row's normalized integer version (no `v` prefix).
- `received_at_utc`: the winning row's normalized timestamp, formatted as
  **`YYYY-MM-DDTHH:MM:SS.ffffffZ`** — ISO 8601 in UTC with **6-digit
  microsecond precision** and a trailing `Z`. Even if the input had only
  millisecond precision, pad with zeros to 6 digits (e.g.
  `2026-05-12 12:23:00.123` → `2026-05-12T12:23:00.123000Z`).

### Row order (explicit tie-break)

Sort the output by:

1. `tenant_id` ascending (lexicographic).
2. Within the same `tenant_id`, by `entity_id` ascending (lexicographic).
3. Within the same `(tenant_id, entity_id)`, by `event_kind` ascending
   (lexicographic).

### Output format

- Standard CSV with the header row exactly as above.
- `version` is a plain integer (no `v` prefix, no decimal point).
- `received_at_utc` is exactly `YYYY-MM-DDTHH:MM:SS.ffffffZ` (always 6-digit
  microseconds, always `Z` suffix). No whitespace.
- UTF-8 encoded. Trailing newline at end of file.
