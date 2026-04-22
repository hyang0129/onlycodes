# Task: Delivery Route — Small Travelling Salesman

A same-day delivery dispatcher has 11 drop-off points and one depot (index 0). A
driver leaves the depot, visits every drop-off exactly once, and returns to the
depot. Cost between any two points is the straight-line Euclidean distance.

**Find the tour starting and ending at the depot that minimizes total travel
distance.**

## Input

Read `stops.json` from your working directory:

```json
{
  "depot": 0,
  "points": [
    [x0, y0],
    [x1, y1],
    ...
  ]
}
```

- `points`: list of 12 `[x, y]` float coordinates (depot + 11 drop-offs), indices
  0 to 11.
- `depot`: integer index of the depot (always 0).

## Output

Write `output/tour.json`:

```json
{
  "tour_length": <float>,
  "tour": [0, <perm of 1..11>, 0]
}
```

- `tour`: a list of `N+1` integers starting AND ending at the depot index, with
  every other index appearing exactly once.
- `tour_length`: total Euclidean distance of that tour. Must match the provided
  `tour` (within 1e-6 relative tolerance) AND must equal the optimal tour length
  (within 1e-6 relative tolerance).

## Requirements

- The tour must be **globally optimal**. With 12 points, Held–Karp (bitmask DP)
  runs in `O(2^N * N^2)` and is well under a second in pure Python.

## Verification

Run `python verify.py` to check your output has the correct shape before submitting.
