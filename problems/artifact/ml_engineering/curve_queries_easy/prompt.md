# Learning Curve Queries — Easy

You have a file `experiments.csv` containing per-step training metrics from
50 parallel training runs. Rows are in **(run_id, step) order**: all steps for
`run_00` appear first in step order, then all steps for `run_01`, and so on.

**File size:** ~5 MB, 100 000 rows (50 runs × 2 000 steps per run).

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

## Task

Compute **1 query**:

### Q1 — `best_val_loss_per_run`

For each of the 50 runs: the **minimum `val_loss`** across all steps.

## Output

Write `output/answers.json` as a JSON object with exactly one key:

```json
{
  "best_val_loss_per_run": {
    "run_00": <float>,
    "run_01": <float>,
    ...
    "run_49": <float>
  }
}
```

All 50 run IDs must be present. Values must be accurate to within 1e-3.

## Verification

Run `python verify.py` to check the output structure before submitting.
