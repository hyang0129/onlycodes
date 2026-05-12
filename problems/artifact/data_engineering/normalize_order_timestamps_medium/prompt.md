# Normalize Order Timestamps Across Three Fulfilment Centres

## Background

Three fulfilment centres each chose their own timestamp wire format when
they joined the order system, and nobody has fixed it. The combined
`orders.csv` therefore contains three different encodings of the same
underlying UTC instant, plus some rows that downstream consumers want
filtered out anyway. BI wants a single CSV where every timestamp is
written in one canonical UTC form and the unwanted rows are gone.

The workspace contains a single file:

- `orders.csv` — the raw export.

## Source file schema (`orders.csv`)

| Column | Type | Notes |
|---|---|---|
| `order_id` | string | unique order identifier, e.g. `ord-000123`. Always present, unique. |
| `region` | string | exactly one of `na`, `eu`, `apac`. Always present. |
| `status` | string | one of `placed`, `fulfilled`, `cancelled`. Always present, lowercase. |
| `placed_at` | string | timestamp in one of the three formats below, **or empty**. |

### `placed_at` format rules

The value may have **leading and/or trailing whitespace**; strip it before
inspecting. After stripping, it is either empty or matches exactly one of
the three formats:

1. **ISO 8601 with an explicit numeric offset**, e.g.
   `2026-04-01T14:23:00+02:00` or `2026-04-01T09:00:00-05:00`. The offset
   is always `±HH:MM` (never `Z`, never a name). Convert to UTC.

2. **Epoch milliseconds** — a plain integer string of length exactly 13,
   e.g. `1743514025123`. Treat as a millisecond offset from the Unix
   epoch in UTC. The millisecond fraction is then **dropped** (truncate
   toward second precision; see Output rules).

3. **Slash-format date+time with a named timezone abbreviation**, e.g.
   `04/01/2026 09:23:00 EST`. The date is `MM/DD/YYYY` (US convention).
   The recognised abbreviations and their fixed UTC offsets are:

   | Abbreviation | UTC offset |
   |---|---|
   | `UTC` | `+00:00` |
   | `EST` | `-05:00` |
   | `EDT` | `-04:00` |
   | `PST` | `-08:00` |
   | `PDT` | `-07:00` |

   The wall-clock time in the named zone, plus the offset above, gives
   the UTC instant. No daylight-savings inference is required — the
   abbreviation is the authoritative offset.

Format detection is per-row and unambiguous. Apply these checks **in order**
to the stripped value:

1. If the value is composed entirely of ASCII digits `0-9`, it is
   **epoch milliseconds** (format 2).
2. Else if the value contains a `/`, it is the **slash-format** (format 3);
   the trailing token is one of the abbreviations listed above.
3. Otherwise it is **ISO 8601 with numeric offset** (format 1).

Apply the checks in this order. Do not branch on the substring `T`
alone — the abbreviation `UTC` also contains the letter `T`, so a naive
`"T" in value` check would misclassify slash-format rows whose
abbreviation is `UTC`.

## Your task

Produce `output/orders_normalized.csv` with **exactly these columns, in
this order**:

```
order_id,region,status,placed_at_utc
```

Apply the following pipeline:

### Step 1 — Filter

Drop any row where:

- `status` equals `cancelled`, **or**
- `placed_at` is empty after stripping whitespace.

Every other row survives.

### Step 2 — Normalize

For each surviving row:

- Parse `placed_at` using the rules above.
- Format the result as **`YYYY-MM-DDTHH:MM:SSZ`** — second precision,
  trailing `Z`, no offset, no fractional seconds. For the epoch-ms input
  this means dropping the millisecond component (floor toward the second).

`order_id`, `region`, `status`: copy through unchanged.

### Row order (explicit tie-break)

Sort the output by `order_id` ascending (lexicographic). `order_id` is
unique in the input, so this fully determines row order.

### Output format

- Standard CSV with the header row exactly as above.
- `placed_at_utc` is exactly `YYYY-MM-DDTHH:MM:SSZ`. No whitespace, no
  fractional seconds, always `Z` (never `+00:00`).
- UTF-8 encoded. Trailing newline at end of file.
