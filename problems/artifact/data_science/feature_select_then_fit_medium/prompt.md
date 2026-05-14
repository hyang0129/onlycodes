# Correlation-Based Feature Selection → Fit → Evaluate

## Background

You have a tabular regression dataset with ten candidate features and
one target. Most features are weakly correlated with the target
(noise); a few are informative (signal). Pick the informative features
by Pearson correlation, fit a linear regression on just those
features, and report the in-sample RMSE alongside the selected feature
names.

The workspace contains:

- `signals.csv` — a CSV with columns
  `x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, y`. All columns are
  numeric (floats), no missing values.

## Your task

Select the features whose **absolute Pearson correlation with `y` is
at least 0.30**, fit a linear regression using only those features
against `y`, and report the in-sample RMSE on the full dataset along
with the selected feature names. Then write `output/result.json`.

The dataset is engineered for wide separation: every feature has
`|r|` either above 0.40 (signal) or below 0.20 (noise) — nothing
lands in the borderline band — so the 0.30 threshold is unambiguous
regardless of which Pearson implementation you reach for.

### Output

```json
{
  "selected_features": ["x1", "x3", "x5", ...],
  "rmse": <float>
}
```

`selected_features` must be **sorted in ascending lexicographic
order** on disk (so `"x10"` comes after `"x1"` and before `"x2"` by
string comparison; the grader checks both set-equality and on-disk
sort order). Extra fields and missing fields are both rejected.

### Pinned details (load-bearing for grading)

1. **Selection rule**: include feature `xi` if and only if
   `|pearson_r(xi, y)| >= 0.30`. Use the unbiased estimator (the
   default for `pandas.DataFrame.corr`, `numpy.corrcoef`, and
   `scipy.stats.pearsonr` — all three agree to floating-point noise
   on this dataset).
2. **Regressor**: `sklearn.linear_model.LinearRegression()` with its
   default constructor.
3. **Fit scope**: all rows of the dataset — no train/test split.
4. **Metric**: in-sample RMSE on the same rows the model was fit on,
   defined as `sqrt(mean((y_pred - y_true) ** 2))`.

Tolerance: `selected_features` is checked as a set (exact match);
`rmse` is checked within ±1e-4. Scoring is all-or-nothing.
