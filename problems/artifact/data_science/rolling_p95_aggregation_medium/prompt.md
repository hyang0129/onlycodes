# Rolling P95 Latency with Threshold Flagging

## Background

You have an hourly time series of request latencies, and you want
the trailing 24-hour rolling 95th percentile — then flag the hours
where that rolling P95 exceeds a 200ms SLO.

The workspace contains:

- `latency.csv` — columns `t, latency_ms`. `t` is a sequential
  integer hour index from 0 to N-1 (rows are in `t` order on disk;
  do not re-sort). `latency_ms` is a non-negative float. No missing
  values.

## Your task

Compute the trailing 24-hour rolling P95 for each `t` where the
window is complete, flag rows whose rolling P95 exceeds 200.0, and
write `output/result.json`.

### Output

```json
{
  "rolling": [
    {"t": <int>, "rolling_p95": <float>},
    ...
  ],
  "flagged_ts": [<int>, <int>, ...]
}
```

- `rolling` must be **sorted ascending by `t`** and contain exactly
  one entry per `t` where the rolling window is complete (`t >= 23`).
- `flagged_ts` must be **sorted ascending** and contain exactly the
  `t` values from `rolling` for which `rolling_p95 > 200.0`.

Extra top-level fields and missing fields are both rejected.

### Pinned details (load-bearing for grading)

1. **Window**: trailing, length 24. For row `t`, the window is the
   24 rows at indices `t-23..t` inclusive — i.e. the current row and
   the 23 immediately prior. This matches `series.rolling(window=24)`
   with `min_periods=24` (the default).
2. **Percentile**: 95th percentile of the 24 window values, computed
   with **linear interpolation** — the default in
   `numpy.quantile(arr, 0.95)`, `numpy.percentile(arr, 95)`, and
   `pd.Series.rolling(window=24).quantile(0.95, interpolation="linear")`.
3. **Boundary**: rows with `t < 23` have an incomplete window. **Do
   not emit those rows in `rolling`** and never include them in
   `flagged_ts`.
4. **Flag rule**: a row's `t` belongs in `flagged_ts` iff
   `rolling_p95 > 200.0` (strict `>`). The dataset is engineered so
   the rolling P95 is either ≪ 180 or ≫ 220 — no row's P95 sits in
   the (180, 220) borderline band, so the strict/non-strict choice
   does not change the answer.

Tolerance: `t` exact integer; `rolling_p95` within ±0.01 (the
relaxed percentile tolerance, per the category convention).
`flagged_ts` is checked as an exact integer set against the
reference. Scoring is all-or-nothing.
