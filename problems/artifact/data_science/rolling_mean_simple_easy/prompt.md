# Trailing 7-Day Rolling Mean

## Background

You have a daily-frequency time series of a numeric quantity, and you
want the standard trailing 7-day rolling mean — useful as a low-pass
smoother for daily metrics.

The workspace contains:

- `daily.csv` — columns `t, value`. `t` is a sequential integer day
  index from 0 to N-1 (rows are in `t` order on disk; do not re-sort).
  `value` is a float. No missing values.

## Your task

Compute the trailing 7-row rolling mean for each `t` where the window
is complete, and write `output/result.json`.

### Output

```json
{
  "rolling": [
    {"t": <int>, "rolling_mean": <float>},
    ...
  ]
}
```

`rolling` must be **sorted ascending by `t`** and contain exactly one
entry per `t` where the rolling window is complete. Extra top-level
fields and missing fields are both rejected.

### Pinned details (load-bearing for grading)

1. **Window**: trailing, length 7. For row `t`, the window is the 7
   rows at indices `t-6, t-5, t-4, t-3, t-2, t-1, t` — i.e. the
   current row and the six immediately prior. This matches the pandas
   default: `series.rolling(window=7).mean()`.
2. **`min_periods`**: 7 (the default for `rolling(window=7)` — a
   value is emitted only when the window is fully populated).
3. **Boundary**: rows with `t < 6` have an incomplete window. **Do
   not emit those rows.** The output has exactly `N - 6` entries.
4. **`rolling_mean`**: arithmetic mean of the 7 window values
   (`sum / 7`).

Tolerance: `t` exact integer; `rolling_mean` within ±1e-4. Scoring is
all-or-nothing.
