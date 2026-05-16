# Pairwise Mann-Whitney with Bonferroni Correction

## Background

You have a CSV of numeric measurements split across four groups, and
you want to know which pairs of groups have distributionally
different values. Run a two-sided Mann-Whitney U test on every pair
and decide using **Bonferroni-corrected** significance at family-wise
α = 0.05.

The workspace contains:

- `measurements.csv` — columns `subject_id, group, value`. `group` is
  a string label drawn from `{"A", "B", "C", "D"}`. `value` is a
  float. No missing values. Every group has at least 40 rows.

## Your task

For every unordered pair of distinct groups, compute the Mann-Whitney
U test, apply Bonferroni correction, and write `output/result.json`.

### Output

```json
{
  "alpha":          0.05,
  "alpha_corrected": <float>,
  "n_pairs":        <int>,
  "pairs": [
    {
      "group_a":    "<name>",
      "group_b":    "<name>",
      "n_a":        <int>,
      "n_b":        <int>,
      "U":          <float>,
      "pvalue":     <float>,
      "reject_null":<bool>
    },
    ...
  ]
}
```

`pairs` must contain exactly **one entry per unordered pair of
distinct groups** present in `measurements.csv`. With four groups
that is six pairs. Entries must be **sorted in ascending
lexicographic order by `(group_a, group_b)`**. Extra top-level fields
and missing fields are both rejected.

### Pinned details (load-bearing for grading)

These are the choices the dataset is *not* engineered to be robust
against — pin them or the U statistic and decision will diverge from
the reference.

1. **Group set**: the four distinct groups that appear in the
   `group` column.
2. **Pair convention**: in every output entry, `group_a < group_b` by
   Python string comparison. So you'll have e.g. `("A", "B")` but
   never `("B", "A")`. Six pairs total: AB, AC, AD, BC, BD, CD.
3. **Test call**: `scipy.stats.mannwhitneyu(values_a, values_b,
   alternative="two-sided", use_continuity=True, method="auto")` —
   with `values_a` as the **first** argument (`group_a`'s values)
   and `values_b` as the second. The returned `U` (the test
   statistic for the first sample, which is what
   `MannwhitneyuResult.statistic` returns in scipy ≥ 1.7) and
   `pvalue` are reported as-is.
4. **`n_a`, `n_b`**: row counts for `group_a` and `group_b`
   respectively.
5. **Bonferroni correction**: `alpha_corrected = 0.05 / n_pairs`
   where `n_pairs = 6` for four groups. `reject_null` is `True` iff
   `pvalue < alpha_corrected` (strict).
6. **Dataset separation**: each pair's p-value is engineered to be
   either ≪ alpha_corrected (sig) or ≫ 0.10 (not sig); no pair sits
   in the borderline band.

Tolerance: `U` within ±1e-4; `pvalue` checked with
`math.isclose(rel_tol=1e-3, abs_tol=1e-15)`; `alpha` is exactly
`0.05` (within ±1e-12); `alpha_corrected` is `0.05/6` (within
±1e-12); `n_pairs`, `n_a`, `n_b` exact integers; `reject_null` exact
boolean. Pair set is an exact match. Scoring is all-or-nothing.
