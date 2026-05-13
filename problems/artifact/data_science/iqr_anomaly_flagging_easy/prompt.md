# Tukey IQR Anomaly Flagging

## Background

You have a CSV of numeric measurements and need to flag the outliers
using the standard Tukey IQR rule: anything outside
`[Q1 - 1.5*IQR, Q3 + 1.5*IQR]` is an outlier.

The workspace contains:

- `measurements.csv` — columns `id, value`. `id` is a unique integer
  row identifier (not necessarily sequential, not necessarily sorted).
  `value` is a float. No missing values.

The dataset is engineered for wide separation: outlier `value`s are
several IQRs outside the fence, and inliers all sit well within it —
so the cutoff is unambiguous regardless of which quantile interpolation
method you pick.

## Your task

Identify the outlier rows by the Tukey 1.5×IQR rule and write
`output/result.json` with their `id`s.

### Output

```json
{
  "flagged_ids": [<int>, <int>, ...]
}
```

`flagged_ids` must be **sorted in ascending integer order**. Empty
list is valid if no rows are outliers (but the dataset is constructed
to contain some). Extra fields and missing fields are both rejected.

### Pinned details (load-bearing for grading)

1. **Quantiles**: `Q1` is the 25th percentile of `value`, `Q3` the
   75th percentile, computed via `numpy.quantile` /
   `pandas.Series.quantile` with the default
   (`method="linear"` / linear interpolation). `IQR = Q3 - Q1`.
2. **Fence**: an outlier is any row with
   `value < Q1 - 1.5*IQR` OR `value > Q3 + 1.5*IQR`.
   The comparators are **strict** (`<` and `>`), but the dataset is
   engineered so no row sits exactly on the fence — the strict/non-
   strict choice does not change the answer.
3. **Index basis**: `flagged_ids` contains the values of the `id`
   column, NOT 0-based row positions in the file.

Grading: `flagged_ids` is checked as an exact integer set against the
reference (and must be sorted ascending on disk). All-or-nothing.
