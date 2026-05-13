# Train/Test Split → Fit → Evaluate

## Background

You have a small tabular regression dataset. Run a standard hold-out
evaluation — split the rows, fit a linear regression on the training
fold, evaluate it on the held-out fold, and report the result.

The workspace contains:

- `housing.csv` — a CSV with columns `x1, x2, x3, x4, x5, y`. All
  columns are numeric (floats), no missing values. Every row is
  independent (no time ordering, no groups).

## Your task

Hold-out evaluate a linear regression model on `housing.csv`: take an
80/20 split, fit on the training fold, predict on the test fold,
report the test-fold RMSE alongside the two fold sizes. Then write
`output/result.json`.

### Output

```json
{
  "rmse": <float>,
  "n_train": <int>,
  "n_test": <int>
}
```

Extra fields and missing fields are both rejected.

### Pinned details (load-bearing for grading)

1. **Split**: `sklearn.model_selection.train_test_split` with
   `test_size=0.2`, `random_state=42`, default shuffle. No
   stratification, no grouping.
2. **Regressor**: `sklearn.linear_model.LinearRegression()` with its
   default constructor.
3. **Metric**: RMSE on the **test fold** (not training, not full
   dataset), defined as `sqrt(mean((y_pred - y_true) ** 2))`.

Tolerance: `n_train` and `n_test` are exact integer matches; `rmse` is
checked within ±1e-4. Scoring is all-or-nothing.
