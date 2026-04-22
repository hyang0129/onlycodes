# Task: Weighted Interval Scheduling — Studio Bookings

Our post-production studio has a single editing bay. We've received 50 booking
requests for the coming month; each has a start time, an end time, and a revenue
figure we'll earn if we accept it. The bay can only service one booking at a time;
two requests whose time ranges overlap cannot both be accepted. End time is
*exclusive* — a booking that ends at time `t` does not conflict with one that
starts at time `t`.

**Choose the subset of requests that maximizes total revenue while respecting
the no-overlap constraint.**

## Input

Read `requests.json` from your working directory:

```json
{
  "requests": [
    {"id": 0, "start": 12, "end": 37, "revenue": 140},
    {"id": 1, "start": 5,  "end": 18, "revenue": 80},
    ...
  ]
}
```

- 50 requests total. Each has a distinct integer `id` (0..49), non-negative
  integer `start` and `end` (with `start < end`), and positive integer `revenue`.

## Output

Write `output/schedule.json`:

```json
{
  "total_revenue": <integer>,
  "chosen_ids": [<list of accepted request ids>]
}
```

- `total_revenue`: sum of `revenue` of the accepted requests. Must equal the
  global optimum.
- `chosen_ids`: (optional but validated if present) list of accepted ids — no
  duplicates, no overlap, and their revenue sum must equal `total_revenue`.

## Requirements

- The `total_revenue` must be **globally optimal**. The classical solution sorts
  by end time and uses DP with binary search over the "last-compatible" predecessor;
  it runs in `O(n log n)`. Greedy-by-revenue is NOT optimal for this problem.

## Verification

Run `python verify.py` to check your output has the correct shape before submitting.
