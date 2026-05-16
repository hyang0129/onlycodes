# Learning Curve Queries — Hard

You have a file `experiments.csv` containing per-step training metrics from
50 parallel training runs. Rows are in **(run_id, step) order**: all steps for
`run_00` appear first in step order, then all steps for `run_01`, and so on.

**File size:** ~100 MB, 2 000 000 rows (50 runs × 40 000 steps per run).

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
The remaining ~70% converge and stay near their minimum.

**Note on file size:** At ~100 MB, this file must be processed
programmatically. Reading it into memory at once with pandas is fine.
Streaming line-by-line also works. Choose what fits your environment.

## Task

Compute **5 queries**:

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

### Q4 — `overfit_onset_per_run`

For each run: the **first step strictly after the best-val-loss step** where
`val_loss[step] > 1.10 × best_val_loss[run]`. If no such step exists
(the run never overfits that badly), output `-1`.

The "best-val-loss step" is the step at which `val_loss` is first minimized
for that run (the earliest step achieving the minimum).

### Q5 — `best_run_overall`

The `run_id` (string) with the **lowest `best_val_loss`** across all 50 runs
(i.e. the run_id whose Q1 value is smallest).

## Output

Write `output/answers.json` as a JSON object with exactly five keys:

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
  "mean_train_val_gap": <float>,
  "overfit_onset_per_run": {
    "run_00": <int>,
    ...
    "run_49": <int>
  },
  "best_run_overall": <string>
}
```

All 50 run IDs must be present in each dict-valued key. Float values accurate
to within 1e-3. Integer step values must be exact. `best_run_overall` is an
exact string (e.g. `"run_17"`).

## Verification

Run `python verify.py` to check the output structure before submitting.
