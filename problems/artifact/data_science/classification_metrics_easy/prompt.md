# Binary Classification Metrics

## Background

You have a CSV of binary classification predictions paired with their
ground-truth labels. Compute the four standard binary-classification
metrics — accuracy, precision, recall, and F1 — for the positive class
and report them.

The workspace contains:

- `predictions.csv` — columns `id, y_true, y_pred`. Both `y_true` and
  `y_pred` are integers in `{0, 1}`. No missing values. `id` is a
  unique row identifier; you don't need it for the computation.

## Your task

Compute the four metrics treating **class `1` as the positive class**,
then write `output/result.json`.

### Output

```json
{
  "accuracy": <float>,
  "precision": <float>,
  "recall": <float>,
  "f1": <float>
}
```

Extra fields and missing fields are both rejected.

### Pinned details (load-bearing for grading)

1. **Positive class**: `1`. Precision, recall, and F1 are computed
   with respect to predictions of `1` (i.e. `pos_label=1`, the sklearn
   default for binary metrics).
2. **Definitions**:
   - `accuracy = (TP + TN) / N`
   - `precision = TP / (TP + FP)`
   - `recall = TP / (TP + FN)`
   - `f1 = 2 * precision * recall / (precision + recall)`

   where TP, FP, FN, TN are counted treating `1` as positive. The
   dataset is constructed so all four denominators are non-zero —
   you do not need to handle the zero-division edge case.
3. **No threshold step**: `y_pred` is already a hard prediction in
   `{0, 1}`. Do not threshold it.

Tolerance: each of the four floats is checked within ±1e-4. Scoring
is all-or-nothing.
