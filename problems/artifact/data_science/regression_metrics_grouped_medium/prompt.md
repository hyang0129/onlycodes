# Per-Group Regression Metrics

## Background

You have a CSV of regression predictions paired with ground-truth
values and a group label. Compute the three standard regression
metrics — RMSE, MAE, and R² — separately for each group, and also
report the overall (pooled-across-groups) values.

The workspace contains:

- `predictions.csv` — columns `id, group, y_true, y_pred`. `id` is a
  unique row identifier (not needed for the computation). `group` is
  a string label drawn from a small fixed set. `y_true` and `y_pred`
  are floats. No missing values. Every group has at least 30 rows.

## Your task

Compute per-group RMSE, MAE, and R², plus the same three metrics
pooled across all rows, then write `output/result.json`.

### Output

```json
{
  "per_group": [
    {"group": "<name>", "n": <int>, "rmse": <float>, "mae": <float>, "r2": <float>},
    ...
  ],
  "overall": {"n": <int>, "rmse": <float>, "mae": <float>, "r2": <float>}
}
```

`per_group` must be **sorted in ascending lexicographic order by
`group`**. Group names not present in the input must not appear in
the output, and every group present in the input must have exactly
one entry. Extra top-level fields and missing fields are both
rejected.

### Pinned details (load-bearing for grading)

1. **Definitions** (standard sklearn conventions):
   - `rmse = sqrt(mean((y_pred - y_true) ** 2))`
   - `mae  = mean(|y_pred - y_true|)`
   - `r2   = 1 - sum((y_true - y_pred)^2) / sum((y_true - mean(y_true))^2)`,
     where `mean(y_true)` is the mean over the rows being scored
     (i.e. per-group R² uses the per-group mean of `y_true`; overall
     R² uses the overall mean). This matches
     `sklearn.metrics.r2_score`.
2. **Pooling**: the `overall` block is computed on **all rows
   concatenated**, not as an average of the per-group values. Equivalent
   to passing the full `y_true`/`y_pred` arrays to the metric
   functions in one call.
3. **`n` is the row count** in that group (or overall), not a
   distinct-value count.

Tolerance: each of the float fields (`rmse`, `mae`, `r2`) is checked
within ±1e-4. `n` is an exact integer match. Group set is an exact
string-set match. Scoring is all-or-nothing.
