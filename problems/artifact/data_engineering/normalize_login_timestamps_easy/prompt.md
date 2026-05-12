# Normalize Login Event Timestamps

## Background

The auth service emits one row per successful login into `login_events.csv`.
The two regional clusters disagree on how to format the `login_at` column:

- **`us-east`** writes ISO 8601 with a UTC suffix, e.g. `2026-04-01T13:23:45Z`.
- **`eu-west`** writes plain **epoch seconds** as an integer string, e.g.
  `1743514025`.

Both encodings represent the same instant in UTC; the cluster just chose
different wire formats. BI wants a single CSV with all timestamps rewritten
into one canonical UTC ISO 8601 format.

The workspace contains a single file:

- `login_events.csv` — the raw export.

## Source file schema (`login_events.csv`)

| Column | Type | Notes |
|---|---|---|
| `event_id` | string | unique event identifier, e.g. `evt-000123`. Always present. |
| `user_id` | string | user identifier, e.g. `u-00042`. Always present. |
| `region` | string | exactly one of `us-east`, `eu-west`. Always present. |
| `login_at` | string | timestamp in one of the two formats below. Always present, always non-empty, always well-formed. |

### `login_at` format rules

Detect the format **per row**:

- If `login_at` is composed entirely of ASCII digits `0-9` (no `T`, no `-`,
  no `:`, no `+`), treat it as **epoch seconds** in UTC. Length is always
  10 digits in this corpus, but you do not need to hard-code that — the
  digits-only check is sufficient.
- Otherwise, the value is **ISO 8601** with the literal `Z` suffix, in the
  exact form `YYYY-MM-DDTHH:MM:SSZ`. Parse it as UTC.

No timezone conversion is required — both formats already represent UTC.

## Your task

Produce `output/logins_normalized.csv` with **exactly these columns, in
this order**:

```
event_id,user_id,region,login_at_utc
```

Rules:

1. Emit one output row per input row. The input has no duplicates and no
   malformed rows; row count in the output equals row count in the input.
2. `event_id`, `user_id`, `region`: copy through unchanged.
3. `login_at_utc`: the parsed UTC instant rewritten as
   **`YYYY-MM-DDTHH:MM:SSZ`** — second precision, trailing `Z`, no
   fractional seconds, no offset. This is the canonical form for both the
   already-ISO rows (effectively a copy-through) and the epoch-seconds
   rows (decoded then re-encoded).

### Row order (explicit tie-break)

Sort the output by `event_id` ascending (lexicographic). `event_id` is
unique across the input, so this fully determines row order.

### Output format

- Standard CSV with the header row exactly as above.
- `login_at_utc` is exactly `YYYY-MM-DDTHH:MM:SSZ` (always `Z`, never an
  offset). No whitespace.
- UTF-8 encoded. Trailing newline at end of file.
