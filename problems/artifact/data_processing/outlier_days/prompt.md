# Outlier Days by Region and Product

Ops wants a daily anomaly report: for each `(region, product)` series of daily
unit sales, flag any day whose sales are far from the recent "normal" using
a robust (median + MAD) metric.

You are given `workspace/sales.csv` with the header row:

```
region,product,date,units_sold
```

- `region` — string, one of a small set.
- `product` — string SKU code.
- `date` — ISO `YYYY-MM-DD`.
- `units_sold` — integer ≥ 0.

Every `(region, product)` series is **dense**: one row per day, no gaps, for
a contiguous span. Different series may cover different spans. The input is
not pre-sorted.

## Task

For each `(region, product)` series independently, compute the following for
every day `d` in the series:

- **Trailing window** = the 14 calendar days strictly before `d` (i.e. the
  rows for dates `d-14, d-13, ..., d-1`). If `d` is one of the first 14 days
  in the series, skip it — it has no full window. Do NOT use smaller-window
  fallbacks; skip the day entirely.
- **Median** of the window's `units_sold` values — call it `m`.
- **MAD** = median of `|x - m|` over the same 14 window values — call it
  `mad`. (Median Absolute Deviation, not scaled.)
- **Modified z-score** for day `d`: if `mad > 0`, `z = 0.6745 * (units_d - m) / mad`.
  If `mad == 0`, then: if `units_d == m`, `z = 0.0`; otherwise
  `z = +9999.0` (saturated positive) if `units_d > m` or `z = -9999.0` if
  `units_d < m`. (This lets constant-series days still flag when the value
  breaks from the constant.)
- A day is an **outlier** iff `|z| >= 3.5`.

Write `output/outliers.jsonl` — one JSON object per outlier day:

```json
{
  "region": "<region>",
  "product": "<sku>",
  "date": "YYYY-MM-DD",
  "units_sold": <int>,
  "window_median": <float>,
  "mad": <float>,
  "modified_z": <float>,
  "direction": "high" | "low"
}
```

- `window_median` and `mad` are output as numbers (rounded to 3 decimals is
  fine; the grader uses a small absolute tolerance).
- `modified_z` is a number rounded to 3 decimals (for saturated cases, emit
  exactly `9999.0` or `-9999.0`).
- `direction` is `"high"` if `z > 0` and `"low"` if `z < 0`. (A z of exactly
  0.0 is never an outlier, so direction is unambiguous in practice.)
- Rows may be in any order; the grader checks by `(region, product, date)`.
- Rows for `(region, product, date)` triples that the grader computes as
  non-outlier will fail the grader. Rows missing for outlier days will fail.

## Optional public verifier

`workspace/verify.py` exposes `verify(artifact_path: Path)` — shape only.

## Notes

- ~80 `(region, product)` series, each spanning ~120 days → ~9,600 rows.
- `pandas`/`numpy`/`scipy`/`sklearn` available.
- No network I/O. Keep peak memory sensible — this dataset easily fits, but
  don't materialize massive intermediate structures.
