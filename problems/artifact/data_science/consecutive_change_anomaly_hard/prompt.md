# Consecutive-Change Run Anomalies

## Background

You have a sequential time-series CSV of a price-like quantity. Day-
to-day changes are normally small (well under 1%), but occasionally
the series goes through a short stretch of large consecutive moves —
either up or down. Identify the rows that close such a stretch.

The workspace contains:

- `series.csv` — columns `t, value`. `t` is a sequential integer time
  index from 0 to N-1 (rows are in `t` order on disk; do not re-sort).
  `value` is a strictly positive float (so `pct_change` is always
  well-defined for `t >= 1`). No missing values.

## Your task

Flag every row that **closes a run of 3 consecutive periods of
large-magnitude relative change**, and write `output/result.json`
with their `t` values.

### Output

```json
{
  "flagged_ts": [<int>, <int>, ...]
}
```

`flagged_ts` must be **sorted ascending**. Extra fields and missing
fields are both rejected.

### Pinned details (load-bearing for grading)

These are the choices the dataset is *not* engineered to be robust
against — pin them or you'll match the wrong rows.

1. **Percent change definition**: for row `t >= 1`,
   `pct_change[t] = (value[t] - value[t-1]) / value[t-1]`. Row `t=0`
   has no `pct_change`. Treat its `pct_change` as undefined
   (effectively `NaN`, NOT zero).
2. **"Large-magnitude" rule**: a single period is "large" iff
   `abs(pct_change[t]) > 0.02` (i.e. > 2% in absolute value, either
   sign). The comparator is **strict** `>`, but the dataset is
   engineered so no period's `|pct_change|` lands near 0.02 — the
   strict/non-strict choice does not change the answer.
3. **Run definition**: row `t` is a flag iff **all three** of
   `pct_change[t-2]`, `pct_change[t-1]`, `pct_change[t]` are
   large-magnitude. (I.e. row `t` closes a run of three consecutive
   large-magnitude periods.) The three periods do NOT need to share
   sign — a `+spike, -spike, +spike` cluster qualifies just as much
   as a monotonic run.
4. **Boundary**: rows with `t < 3` cannot close a 3-period run
   (because `pct_change[t-2]` would reference `t=-1` for `t=1`, and
   the t=0 row has no pct_change). Never put `t < 3` in the output.
5. **Index basis**: the `t` column value, equal to the 0-based row
   position in the file.

Grading: `flagged_ts` is checked as an exact integer set against the
reference (and must be sorted ascending on disk). All-or-nothing.

### Worked illustration

Suppose `pct_change` for `t=0..6` is

```
t=0: NaN       (no pct_change)
t=1: +0.001    (small)
t=2: +0.045    (LARGE)
t=3: -0.038    (LARGE)
t=4: +0.052    (LARGE)
t=5: -0.041    (LARGE)
t=6: +0.002    (small)
```

Then `t=4` closes a 3-period run (`t=2, 3, 4` all large), and `t=5`
also closes a 3-period run (`t=3, 4, 5` all large). `t=2` and `t=3`
do **not** qualify because they don't have two large predecessors.
`t=6` doesn't qualify because the period at `t=6` is small. Output
would be `[4, 5]`.
