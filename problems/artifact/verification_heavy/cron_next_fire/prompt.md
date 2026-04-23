# Task: Compute the next cron fire time

Our job scheduler currently uses a third-party cron library that is abandoned
and flaky around DST transitions. Before we replace it, we need a small,
well-tested reference implementation of "given a cron expression and a
reference instant, what is the next instant the job would fire?"

Implement `next_fire(expr: str, after: datetime) -> datetime`. The returned
datetime must be **strictly after** `after` (equal is not a match) and must
be the earliest matching instant.

## Cron expression format

Five space-separated fields, in order:

```
minute hour day-of-month month day-of-week
```

Each field supports:

- `*` — any value in the field's range.
- A single integer — exact match.
- A comma-separated list, e.g. `1,5,30`.
- A range `a-b`, inclusive.
- A step `*/n`, `a-b/n`, or `a/n` — match every `n`th value starting from `a`
  (or from the field's minimum if the base is `*`). With a single start value
  `a/n`, the step runs from `a` up to the field's maximum (e.g. in the
  minute field, `0/20` ≡ `0,20,40`).

Field ranges:

| Field | Range |
|-------|-------|
| minute | 0–59 |
| hour | 0–23 |
| day-of-month | 1–31 |
| month | 1–12 |
| day-of-week | 0–6 (0 = Sunday) |

### Day-of-month / day-of-week combination

If **both** day-of-month and day-of-week are restricted (not `*`), the schedule
fires when **either** one matches — classic Vixie-cron "OR" semantics. If one
is `*` and the other is restricted, only the restricted one applies.

### Other rules

- Seconds are always treated as 0. Returned datetimes have `second=0,
  microsecond=0`.
- Inputs are naive datetimes (no tzinfo). No DST handling needed.
- Invalid month/day combinations (e.g. Feb 30) are simply skipped — the
  function looks for the next valid combination.
- You may assume cron expressions are syntactically valid; do not do error
  handling.
- Worst-case lookahead is 4 years; fail-safe by raising `ValueError` if no
  match is found within that window.

## Examples

Given `after = datetime(2024, 1, 1, 12, 0, 0)`:

| Expression | Meaning | Next fire |
|------------|---------|-----------|
| `* * * * *` | every minute | `2024-01-01 12:01:00` |
| `0 * * * *` | top of every hour | `2024-01-01 13:00:00` |
| `0 0 * * *` | daily midnight | `2024-01-02 00:00:00` |
| `30 14 * * *` | 14:30 daily | `2024-01-01 14:30:00` |
| `0 0 1 * *` | 1st of month | `2024-02-01 00:00:00` |
| `*/15 * * * *` | every 15 min | `2024-01-01 12:15:00` |
| `0 9-17 * * 1-5` | hourly 9–17 M–F | `2024-01-01 13:00:00` |

## Output

Write your implementation to `output/solution.py`:

```python
from datetime import datetime

def next_fire(expr: str, after: datetime) -> datetime:
    ...
```

Standard library only (`datetime`, `calendar`, etc. are fine). No `croniter`
or other third-party packages.

## Verification

Run `python verify.py` to check structural shape. The hidden grader runs 20
fixed cases including month rollovers, leap years, and step values.
