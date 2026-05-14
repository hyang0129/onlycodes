# Welch's Two-Sample t-Test

## Background

You have a CSV of measurements split across a control group and a
treatment group, and you want to know whether the treatment mean
differs from the control mean.

The workspace contains:

- `measurements.csv` — columns `subject_id, group, value`. `group` is
  the string `"control"` or `"treatment"`. `value` is a float. No
  missing values. Rows are interleaved (not pre-grouped). Both groups
  have at least 100 rows.

## Your task

Run a two-sample t-test comparing the two groups and write
`output/result.json`.

### Output

```json
{
  "n_control":     <int>,
  "n_treatment":   <int>,
  "mean_control":  <float>,
  "mean_treatment":<float>,
  "statistic":     <float>,
  "pvalue":        <float>,
  "reject_null":   <bool>
}
```

Extra fields and missing fields are both rejected.

### Pinned details (load-bearing for grading)

1. **Test**: Welch's two-sample t-test (`scipy.stats.ttest_ind` with
   `equal_var=False`), `alternative="two-sided"` (the default).
2. **Argument order**: pass `treatment` values as the **first**
   argument and `control` values as the **second** — i.e.
   `ttest_ind(treatment_values, control_values, equal_var=False)`.
   The sign of `statistic` depends on this order; the reference
   convention is positive when treatment mean > control mean.
3. **`mean_control`, `mean_treatment`**: arithmetic mean of `value`
   within each group.
4. **`reject_null`**: `True` iff `pvalue < 0.05` (strict). The
   dataset is engineered so the p-value is either many orders of
   magnitude below 0.05 or comfortably above 0.10 — no borderline
   case.

Tolerance: `statistic` within ±1e-4; `pvalue` within ±1e-6;
`mean_*` within ±1e-4; `n_*` exact integer; `reject_null` exact
boolean. Scoring is all-or-nothing.
