# Expanding Percentile Snapshots Across Three Metrics

## Background

You have a multi-metric time series, and you want **expanding-window
percentile snapshots** at four checkpoint times — useful for running
"to-date" SLA accounting where each snapshot summarizes everything
observed so far.

The workspace contains:

- `metrics.csv` — columns `t, metric_a, metric_b, metric_c`. `t` is
  a sequential integer time index from 0 to N-1 (rows are in `t`
  order on disk; do not re-sort). Each metric column is a float. No
  missing values. `N = 200`.

## Your task

At each of four fixed checkpoints, compute the expanding p50, p90,
and p99 of each of the three metrics (using all rows from `t=0`
through the checkpoint inclusive), then write `output/result.json`.

Checkpoints: `t in [49, 99, 149, 199]` — the 50th, 100th, 150th, and
200th observations (1-indexed in the everyday sense, but the
`t` values themselves are 0-indexed).

### Output

```json
{
  "checkpoints": [
    {
      "t": <int>,
      "n_observations": <int>,
      "metrics": [
        {"metric": "metric_a", "p50": <float>, "p90": <float>, "p99": <float>},
        {"metric": "metric_b", "p50": <float>, "p90": <float>, "p99": <float>},
        {"metric": "metric_c", "p50": <float>, "p90": <float>, "p99": <float>}
      ]
    },
    ...
  ]
}
```

`checkpoints` must contain exactly **four** entries, sorted ascending
by `t`. Within each checkpoint, `metrics` must contain exactly
**three** entries, sorted ascending by `metric` name
(`metric_a`, `metric_b`, `metric_c`). Extra top-level fields and
missing fields are both rejected, as are extra/missing fields inside
any nested object.

### Pinned details (load-bearing for grading)

These choices affect the answer; pin them or your numbers will
diverge from the reference even with the right method.

1. **Expanding window**: the window for checkpoint `t = T` is **all
   rows with `t_row <= T`** — i.e. rows `0, 1, 2, ..., T` inclusive,
   for a window size of `T + 1`. This matches the pandas default
   `series.expanding().quantile(q).loc[T]` (with `min_periods=1`).
2. **`n_observations`**: the window size = `T + 1`.
3. **Percentile interpolation**: `numpy.quantile(arr, q)` /
   `numpy.percentile(arr, q*100)` default = `method="linear"`.
   `pd.Series.expanding().quantile(q)` also defaults to linear.
4. **Quantile values**: `p50 = quantile(0.50)`, `p90 = quantile(0.90)`,
   `p99 = quantile(0.99)`.
5. **Per-metric independence**: each metric's percentile is computed
   over **only its own column**, not over the row-aggregate.
6. **Metric ordering**: `metric_a`, then `metric_b`, then `metric_c`
   (ascending lexicographic on the column name).
7. **Checkpoints**: exactly `t in [49, 99, 149, 199]`. Do not emit
   percentiles at any other `t`.

Tolerance: `t` and `n_observations` are exact integers; each
percentile float is checked within ±0.01 (the relaxed percentile
tolerance, per the category convention). Scoring is all-or-nothing.
