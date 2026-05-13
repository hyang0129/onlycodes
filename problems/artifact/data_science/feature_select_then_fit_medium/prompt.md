# Correlation-Based Feature Selection → Fit → Evaluate

## Background

You have a tabular regression dataset with ten candidate features and one
target. Most features are weakly correlated with the target (noise); a few
are informative (signal). Your job is to pick the informative features by
correlation, fit a linear regression using only those features, and report
the in-sample RMSE alongside the selected feature names.

The workspace contains:

- `signals.csv` — a CSV with columns `x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, y`.
  All columns are numeric (floats). There are no missing values.

## Your task

Perform the pipeline below exactly as specified, then write
`output/result.json`.

### Pipeline (run these steps in order)

1. **Load** `signals.csv` with `pandas.read_csv`. The ten feature columns are
   `x1, x2, …, x10`; the target column is `y`.
2. **Compute the Pearson correlation** between each feature and the target.
   The Pearson correlation between two vectors `u` and `v` is:

   ```
   r(u, v) = cov(u, v) / (std(u) * std(v))
   ```

   You may use `pandas.DataFrame.corr(method="pearson")`,
   `numpy.corrcoef`, or `scipy.stats.pearsonr` — all three produce the same
   number to within floating-point noise. Use the unbiased estimator (the
   default for all three).
3. **Select the features** whose absolute Pearson correlation with `y` is at
   least `0.30`. Formally: include feature `xi` if and only if
   `|r(xi, y)| >= 0.30`. The dataset is constructed so that every feature
   has `|r|` either above `0.40` (signal) or below `0.20` (noise) — no
   feature lands in the borderline band `(0.20, 0.40)` — so the threshold
   is unambiguous regardless of which Pearson implementation you use.
4. **Fit** a linear regression using only the selected features as
   predictors and `y` as the target, using
   `sklearn.linear_model.LinearRegression` with its default constructor.
   Fit on **all rows** of the dataset (no train/test split).
5. **Predict** `y` on the same rows the model was fit on (in-sample
   predictions).
6. **Compute the in-sample RMSE** of the predictions against the true `y`.
   Define RMSE explicitly as:

   ```
   RMSE = sqrt( mean( (y_pred - y_true) ** 2 ) )
   ```

### Output

Write `output/result.json` containing **exactly these two fields**:

```json
{
  "selected_features": ["x1", "x3", "x5", ...],
  "rmse": <float>
}
```

Rules:

- `selected_features` — a JSON array of strings, the feature column names
  selected in step 3, **sorted in ascending lexicographic order** (so
  `"x10"` comes after `"x1"` and before `"x2"`, by string comparison).
- `rmse` — the in-sample RMSE computed in step 6, as a JSON number. Do not
  round; emit full precision. The grader tolerates floating-point noise
  within `±1e-4`.
- Extra fields are not allowed. Missing fields are not allowed.
- UTF-8 encoded. Trailing newline optional.

### What the grader checks

The grader re-runs the same pipeline on `signals.csv` and compares your
`result.json`:

- `selected_features` must equal the grader's selection as a set
  (order-insensitive — but it must still be lexicographically sorted on
  disk to make diffs deterministic; the grader checks both).
- `rmse` must be within `±1e-4` of the grader's value.

Scoring is all-or-nothing: any field failing yields score 0.0. Both
matching yields score 1.0.
