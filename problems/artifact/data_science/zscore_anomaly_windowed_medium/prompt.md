# Windowed Z-Score Anomaly Flagging

## Background

You have a sequential time-series CSV. For each row, compute a
z-score against a **trailing window** of recent prior observations,
and flag the row if its z-score exceeds 3.0 in absolute value.

The workspace contains:

- `series.csv` — columns `t, value`. `t` is a sequential integer
  time index from 0 to N-1 (rows are in `t` order on disk; do not
  re-sort). `value` is a float. No missing values.

## Your task

Flag the anomalous rows using the trailing-window z-score rule below
and write `output/result.json` with their `t` values.

### Output

```json
{
  "flagged_ts": [<int>, <int>, ...]
}
```

`flagged_ts` must be **sorted ascending**. Extra fields and missing
fields are both rejected.

### Pinned details (load-bearing for grading)

1. **Window**: for row `t`, the window is the previous 20 rows —
   indices `t-20, t-19, ..., t-1` — and **does not include row `t`
   itself**. Window size is fixed at 20.
2. **Boundary**: rows with `t < 20` have an incomplete window and are
   **not flaggable**. Never put a `t < 20` value in the output.
3. **Window statistics**: `window_mean = mean(window values)`,
   `window_std = std(window values, ddof=1)` (sample std, the pandas
   and numpy default for `rolling().std()` and `numpy.std(ddof=1)`).
4. **Z-score**: `z[t] = (value[t] - window_mean) / window_std`.
5. **Flag rule**: row `t` is anomalous iff `abs(z[t]) > 3.0`. The
   comparator is **strict** `>`, but the dataset is engineered so no
   row's `|z|` lands near 3.0 — the strict/non-strict choice does not
   change the answer.

Grading: `flagged_ts` is checked as an exact integer set against the
reference (and must be sorted ascending on disk). All-or-nothing.
