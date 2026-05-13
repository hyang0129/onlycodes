# Train/Test Split → Fit → Evaluate

## Background

You have a small tabular regression dataset. Your job is to run a standard
hold-out evaluation: split the rows, fit a linear regression on the training
fold, evaluate it on the held-out fold, and report the result.

The workspace contains:

- `housing.csv` — a CSV with columns `x1, x2, x3, x4, x5, y`. All columns are
  numeric (floats). There are no missing values. Every row is independent.

## Your task

Perform the pipeline below exactly as specified, then write
`output/result.json`.

### Pipeline (run these steps in order)

1. **Load** `housing.csv` with `pandas.read_csv`. The five feature columns are
   `x1, x2, x3, x4, x5`; the target column is `y`.
2. **Split** the rows into a training fold and a test fold using
   `sklearn.model_selection.train_test_split` with:
   - `test_size=0.2`
   - `random_state=42`
   - `shuffle=True` (the default)
   No stratification.
3. **Fit** a linear regression on the training fold using
   `sklearn.linear_model.LinearRegression` with its default constructor
   (i.e. `fit_intercept=True`, no other arguments).
4. **Predict** on the test fold's features.
5. **Compute the RMSE** of the test-fold predictions against the test-fold
   true `y` values. Define RMSE explicitly as:

   ```
   RMSE = sqrt( mean( (y_pred - y_test) ** 2 ) )
   ```

   You may use `numpy.sqrt(numpy.mean(...))` or any equivalent expression. Do
   not use a different reduction (no median, no per-feature aggregation).

### Output

Write `output/result.json` containing **exactly these three fields**:

```json
{
  "rmse": <float>,
  "n_train": <int>,
  "n_test": <int>
}
```

Rules:

- `rmse` — the RMSE computed in step 5, as a JSON number. Do not round; emit
  full precision. The grader tolerates floating-point noise within `±1e-4`.
- `n_train` — the integer number of rows in the training fold.
- `n_test` — the integer number of rows in the test fold.
- Field order is not significant (JSON object). Extra fields are not allowed.
- UTF-8 encoded. Trailing newline optional.

### What the grader checks

The grader re-runs the same pipeline on `housing.csv` and compares your
`result.json` field-by-field:

- `n_train` and `n_test` must be exact integer matches.
- `rmse` must be within `±1e-4` of the grader's value.

Scoring is all-or-nothing: any single field failing yields score 0.0. All
three matching yields score 1.0.
