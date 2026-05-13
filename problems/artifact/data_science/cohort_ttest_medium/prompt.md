# Paired t-Test Per Cohort

## Background

You have a CSV of before/after measurements taken on the same set of
subjects across three cohorts. For each cohort, test whether the
within-subject change `(after - before)` differs from zero, and also
report the same test pooled across all cohorts.

The workspace contains:

- `pairs.csv` — columns `subject_id, cohort, before, after`.
  `subject_id` is unique within the file. `cohort` is a string label
  drawn from `{"north", "south", "west"}`. `before` and `after` are
  floats. No missing values. Every cohort has at least 40 rows.

## Your task

For each cohort and for the pooled set of all rows, compute the paired
t-test on `(after - before)`, then write `output/result.json`.

### Output

```json
{
  "per_cohort": [
    {
      "cohort": "<name>",
      "n_pairs":      <int>,
      "mean_diff":    <float>,
      "statistic":    <float>,
      "pvalue":       <float>,
      "reject_null":  <bool>
    },
    ...
  ],
  "overall": {
    "n_pairs":      <int>,
    "mean_diff":    <float>,
    "statistic":    <float>,
    "pvalue":       <float>,
    "reject_null":  <bool>
  }
}
```

`per_cohort` must be **sorted in ascending lexicographic order by
`cohort`** and contain exactly one entry per cohort present in
`pairs.csv`. Extra top-level fields and missing fields are both
rejected.

### Pinned details (load-bearing for grading)

1. **Test**: paired (related-samples) t-test,
   `scipy.stats.ttest_rel(after_values, before_values)`,
   `alternative="two-sided"` (the default). Pass **`after` as the
   first argument and `before` as the second**, so the sign of the
   statistic matches the sign of the mean within-subject change.
2. **`mean_diff`**: arithmetic mean of `(after - before)` across the
   pairs in the relevant scope (per cohort or overall).
3. **`n_pairs`**: count of rows in the scope (each row already
   represents one paired observation).
4. **Pooling**: `overall` is computed on **all rows concatenated**,
   not as an average of per-cohort statistics. It is equivalent to
   passing every row's `after` and `before` to `ttest_rel` in one
   call (with each subject still paired only with their own row).
5. **`reject_null`**: `True` iff `pvalue < 0.05` (strict). The
   dataset is engineered so every test's p-value is either many
   orders of magnitude below 0.05 or comfortably above 0.10 — no
   borderline case.

Tolerance: `statistic` within ±1e-4; `pvalue` checked with
`math.isclose(rel_tol=1e-3, abs_tol=1e-15)` (tight relative match
that still allows the agent to report extremely small p-values
exactly as scipy returns them); `mean_diff` within ±1e-4; `n_pairs`
exact integer; `reject_null` exact boolean. `cohort` is an exact
string-set match. Scoring is all-or-nothing.
