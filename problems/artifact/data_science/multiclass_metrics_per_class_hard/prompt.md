# Per-Class Multiclass Metrics with Macro & Weighted Averages

## Background

You have a CSV of multiclass classification predictions paired with
ground-truth labels over four classes. Compute the per-class
precision, recall, F1, and support, and then compute macro and
weighted averages of precision, recall, and F1 across classes. Also
report overall accuracy.

The workspace contains:

- `predictions.csv` — columns `id, y_true, y_pred`. `id` is a unique
  row identifier (not needed). `y_true` and `y_pred` are integers in
  `{0, 1, 2, 3}` — the four class labels. No missing values.

Class supports are imbalanced by construction, so macro and weighted
averages give meaningfully different numbers.

## Your task

Compute the metrics described above and write `output/result.json`.

### Output

```json
{
  "per_class": [
    {"class": <int>, "support": <int>, "precision": <float>, "recall": <float>, "f1": <float>},
    ...
  ],
  "macro_avg":    {"precision": <float>, "recall": <float>, "f1": <float>},
  "weighted_avg": {"precision": <float>, "recall": <float>, "f1": <float>},
  "accuracy": <float>
}
```

`per_class` must contain **exactly one entry per class label that
appears in `y_true`**, sorted in ascending integer order by `class`.
Extra fields at the top level (or inside the nested objects) are
rejected, as are missing fields.

### Pinned details (load-bearing for grading)

1. **Class set**: the four classes that appear in `y_true` (which is
   `{0, 1, 2, 3}` — verify this from the data). Do not invent a
   class that is not in `y_true`. Every required class is present in
   `y_true`; the dataset is constructed so each class has both true
   positives and false positives, so per-class precision/recall/F1
   are all well-defined.
2. **Definitions** (standard one-vs-rest, matching
   `sklearn.metrics.precision_recall_fscore_support(...,
   average=None)`):
   - Per class `c`:
     - `support_c = #{i : y_true[i] == c}`
     - `precision_c = TP_c / (TP_c + FP_c)` where TP/FP treat class
       `c` as positive
     - `recall_c    = TP_c / (TP_c + FN_c)`
     - `f1_c        = 2 * precision_c * recall_c / (precision_c + recall_c)`
3. **Macro average**: arithmetic mean of the per-class values across
   the four classes — separately for precision, recall, and F1.
   That is, `macro_f1 = mean(f1_c)`, NOT recomputed from `macro_p`
   and `macro_r`. (This matches sklearn's `average='macro'`.)
4. **Weighted average**: per-class values weighted by `support_c`,
   summed and divided by total support. Again computed per-metric:
   `weighted_f1 = sum(support_c * f1_c) / sum(support_c)`, NOT
   recomputed from weighted precision/recall. (This matches sklearn's
   `average='weighted'`.)
5. **Accuracy**: `#{i : y_true[i] == y_pred[i]} / N`. Note that for
   multiclass, sklearn's micro-averaged precision/recall/F1 equal
   accuracy — we report it as `accuracy` rather than as `micro_avg`.

Tolerance: each float field is checked within ±1e-4. `support` and
`class` are exact integer matches. Scoring is all-or-nothing.
