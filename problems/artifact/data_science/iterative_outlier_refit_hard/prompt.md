# Iterative Outlier Refit

## Background

You have a tabular regression dataset with three features and one
target. Most rows are well-described by a linear model; a small
minority are contaminated with a large additive y-shift and should be
excluded from the final fit. Your job is to find those outliers by
iteratively fitting, flagging large-residual rows, dropping them, and
refitting — repeating until the flagged set stops changing — then
report the converged outlier set and the final fit on the cleaned
rows.

The workspace contains:

- `data.csv` — a CSV with columns `x1, x2, x3, y`. All columns are
  numeric (floats), no missing values. The original row order in this
  file defines the row indices the grader will compare against.

## Your task

Run the following analysis and write `output/result.json`.

Iteratively fit a linear regression on the currently-included rows,
predict, compute residuals, flag rows whose **residual z-score has
absolute value greater than 3.0** as outliers, drop them, and refit.
Repeat until the flagged outlier set is identical to the previous
iteration's flagged set; that is the convergence point. The dataset is
engineered for wide separation (inliers sit at `|z| < 2`, outliers at
`|z| > 5`, with nothing in between), so the flag decision is
unambiguous and convergence is reached in a handful of iterations —
cap the loop at 50 as a defensive guard.

### Output

Write `output/result.json` containing **exactly these five fields**:

```json
{
  "outlier_indices": [49, 99, 149, ...],
  "n_iterations": 2,
  "final_intercept": <float>,
  "final_coefficients": [<float>, <float>, <float>],
  "final_rmse": <float>
}
```

### Pinned details (load-bearing for grading)

The dataset is engineered so most algorithmic choices (sample-vs-
population std, σ scope, strict vs non-strict comparator) don't change
the answer. The five pins below DO change the answer and are the
contract you must meet:

1. **Regressor**: `sklearn.linear_model.LinearRegression()` with its
   default constructor. No regularization, no alternative solver.
2. **Coefficient output order**: `final_coefficients` is the
   `model.coef_` array in the column order `[x1, x2, x3]` — match the
   CSV's column order exactly.
3. **`n_iterations` counting**: the value of your iteration counter at
   the moment you detect convergence — i.e. the iteration whose
   flagged set first matches the previous iteration's flagged set
   counts toward `n_iterations`. If iteration 1 flags set S and
   iteration 2 also flags set S, that's `n_iterations = 2`.
4. **Row index basis**: original 0-based positions in `data.csv` (the
   first data row after the header is index 0). Do not shuffle,
   re-sort, or `reset_index` after dropping outliers — the grader
   compares against original-file row indices.
5. **`final_rmse` scope**: in-sample RMSE of the final fit, computed
   over the **inlier rows only** (the rows the final model was fit
   on), with the standard definition
   `sqrt(mean((y_pred - y_true) ** 2))`. Not over the full dataset.

Numeric tolerance: `outlier_indices` is checked as a set (exact match)
but must be **sorted ascending** on disk; `n_iterations` is an exact
integer; the three float fields are checked within ±1e-4. Extra fields
and missing fields are both rejected. Scoring is all-or-nothing.
