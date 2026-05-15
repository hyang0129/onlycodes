# Learning Curve Queries — Medium

You have a file `experiments.csv` containing per-step training metrics from
50 parallel training runs. Rows are in **(run_id, step) order**: all steps for
`run_00` appear first in step order, then all steps for `run_01`, and so on.

**File size:** ~50 MB, 1 000 000 rows (50 runs × 20 000 steps per run).

## CSV columns

| Column | Type | Description |
|---|---|---|
| `step` | int | Training step, 1-indexed |
| `run_id` | str | Run identifier: `"run_00"` … `"run_49"` |
| `train_loss` | float | Training loss at this step |
| `val_loss` | float | Validation loss at this step |
| `lr` | float | Learning rate (constant per run) |

Loss curves are exponentially decaying with noise. Approximately 30% of runs
exhibit late-stage overfitting (val_loss rises after reaching its minimum).

**Note on file size:** At ~50 MB, the CSV is larger than most text viewers
display fully. Read it programmatically (e.g. `pandas.read_csv` or iterate
line by line).

## Task

Compute **3 queries**:

### Q1 — `best_val_loss_per_run`

For each of the 50 runs: the **minimum `val_loss`** across all steps.

### Q2 — `convergence_step_per_run`

For each run: the **first step** where
`val_loss[step] ≤ 1.05 × best_val_loss[run]`.

"First" means the smallest step number satisfying the condition.
`best_val_loss[run]` is the value from Q1 for that run.

### Q3 — `mean_train_val_gap`

The **mean of (val_loss − train_loss)** computed across **all rows** in the
file (not per-run averages; a single global mean).

## Output

Write `output/answers.json` as a JSON object with exactly three keys:

```json
{
  "best_val_loss_per_run": {
    "run_00": <float>,
    ...
    "run_49": <float>
  },
  "convergence_step_per_run": {
    "run_00": <int>,
    ...
    "run_49": <int>
  },
  "mean_train_val_gap": <float>
}
```

All 50 run IDs must be present in each dict. Float values accurate to within
1e-3. Integer step values must be exact.

## Verification

Run `python verify.py` to check the output structure before submitting.
