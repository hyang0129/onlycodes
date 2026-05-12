# Unify Cross-Region Event Logs With Timezone and User Joins

## Background

Three regional analytics pipelines (US, EU, APAC) emit event logs in
**three different schemas** — each team picked their own field names,
timestamp encoding, and user-ID format. Marketing needs one normalized
table joined to user metadata, sorted by UTC timestamp, ready for a
single SQL query.

The workspace contains four files:

- `events_us.jsonl` — JSON-lines, one event per line.
- `events_eu.jsonl` — JSON-lines, one event per line.
- `events_apac.jsonl` — JSON-lines, one event per line.
- `users.csv` — user reference table.

## Source file schemas

### `events_us.jsonl`

One JSON object per line:

```json
{"uid": 42, "ts": 1768498800, "evt": "PageView"}
```

| Field | Type | Notes |
|---|---|---|
| `uid` | integer | the user identifier as a **plain integer**. |
| `ts` | integer | **Unix epoch seconds, UTC.** |
| `evt` | string | event type. Values from the closed vocabulary listed below, **in mixed case** (e.g. `PageView`, `AddToCart`). |

### `events_eu.jsonl`

One JSON object per line:

```json
{"userId": "u-42", "timestamp": "2026-01-15T14:23:00+01:00", "event": "Page View"}
```

| Field | Type | Notes |
|---|---|---|
| `userId` | string | format `u-<n>` — strip the `u-` prefix to recover the integer user id. |
| `timestamp` | string | ISO 8601 **with timezone offset** (e.g. `+01:00`, `+02:00` for DST). Parse and convert to UTC. |
| `event` | string | event type in the closed vocabulary, but **may contain a space** (e.g. `Page View`, `Add To Cart`). |

### `events_apac.jsonl`

One JSON object per line:

```json
{"user_id": "USER_42", "time_local": "2026-01-15T22:23:00", "action": "page_view"}
```

| Field | Type | Notes |
|---|---|---|
| `user_id` | string | format `USER_<n>` — strip the `USER_` prefix to recover the integer user id. |
| `time_local` | string | **Naive ISO 8601, no timezone**. The APAC team always emits in **Asia/Tokyo local time** (`+09:00`). Treat every `time_local` as Tokyo-local and convert to UTC. |
| `action` | string | event type in the closed vocabulary, **already snake_case** (e.g. `page_view`, `add_to_cart`). |

### `users.csv`

| Column | Type | Notes |
|---|---|---|
| `user_id` | integer | the canonical id space — what the other files' uid/userId/user_id all resolve to. |
| `email` | string | not used in the output. |
| `tier` | string | one of `free`, `pro`, `enterprise`. |

## Normalization rules

### Event type — closed vocabulary

The canonical event types are exactly these five (snake_case, lowercase):

```
page_view, add_to_cart, checkout, login, logout
```

Each source file uses a different stylistic convention. Map the input to
the canonical form by **lower-casing and replacing all spaces with
underscores** (so `Page View` → `page_view`, `AddToCart` → `add_to_cart`
after the space rule is applied — see below).

Specifically, the input values that you may see are:

| Source file | Raw values |
|---|---|
| `events_us.jsonl` (`evt`) | `PageView`, `AddToCart`, `Checkout`, `Login`, `Logout` (camel-case, no separator) |
| `events_eu.jsonl` (`event`) | `Page View`, `Add To Cart`, `Checkout`, `Login`, `Logout` (Title Case With Spaces) |
| `events_apac.jsonl` (`action`) | `page_view`, `add_to_cart`, `checkout`, `login`, `logout` (already canonical) |

To normalize uniformly:

1. Insert an underscore before each uppercase letter that follows a
   lowercase letter (so `PageView` → `Page_View`, `AddToCart` →
   `Add_To_Cart`).
2. Replace spaces with underscores.
3. Lowercase the result.

The output must be exactly one of the five canonical values. Rows whose
event type does not normalize to one of the five values must be dropped
(the source files include a small number of typo'd values to test this).

### Timestamp — convert all to UTC

The output timestamp column is in **UTC, ISO 8601, with a trailing `Z`,
to second precision**:

```
2026-01-15T13:23:00Z
```

Conversion rules:

- US (`ts`): treat as Unix epoch seconds UTC → format directly.
- EU (`timestamp`): parse the ISO string (it has an explicit offset) →
  convert to UTC.
- APAC (`time_local`): the string is naive (no offset). Attach
  **Asia/Tokyo (+09:00)** as the source timezone, then convert to UTC.

### User join

The user identifier in the output is the canonical **integer** form. If
the resolved integer user id is **not present** in `users.csv`, drop the
row (it is an orphan).

For rows that survive, attach the user's `tier` from `users.csv` as
`user_tier`.

## Your task

Produce `output/events.csv` with **exactly these columns, in this order**:

```
event_utc_ts,user_id,user_tier,event_type,source_region
```

Where:

- `event_utc_ts` — UTC timestamp in `YYYY-MM-DDTHH:MM:SSZ` format.
- `user_id` — plain integer (no prefix, no padding).
- `user_tier` — one of `free`, `pro`, `enterprise`.
- `event_type` — one of `page_view`, `add_to_cart`, `checkout`, `login`,
  `logout`.
- `source_region` — exactly one of the strings `us`, `eu`, `apac`.

### Row order (explicit tie-break)

Sort by:

1. `event_utc_ts` ascending (string compare is fine because the format
   is lexicographically aligned with chronological order).
2. Within the same timestamp, by `user_id` ascending (numeric).
3. Within the same `(event_utc_ts, user_id)`, by `source_region`
   ascending **lexicographically** — so `apac` < `eu` < `us`.

### Output format

- Standard CSV with the header row exactly as above.
- UTF-8 encoded. Trailing newline at end of file.
- One row per surviving event across all three regional files. Orphan
  users and unknown event types are dropped (not flagged).
