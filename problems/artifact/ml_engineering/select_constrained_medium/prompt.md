# Select the Top-20 Eligible Runs

## Background

A research team ran a large hyperparameter sweep over the last quarter
and exported every run's final metrics to a single CSV. Leadership has
narrowed down the candidates they want to look at by hand to a set of
**hard constraints** on how a run was trained, and within that set they
want **the 20 best by validation accuracy**.

The workspace contains:

- `experiments.csv` — one row per training run, header included

with columns (exactly, in this order):

```
run_id,dataset,val_acc,params_M,lr,dropout,train_hours
```

## Constraints

A run is **eligible** if and only if **all** of the following are true:

| Constraint | Meaning |
|---|---|
| `dataset ∈ {cifar10, imagenet}` | mnist, svhn, and fashion_mnist runs are excluded |
| `params_M ≤ 50` | model has at most 50 million parameters |
| `1e-5 ≤ lr ≤ 1e-3` | learning rate is in this **inclusive** range |
| `train_hours ≤ 24` | training finished within one day |
| `0.1 ≤ dropout ≤ 0.3` | dropout is in this **inclusive** range |

All comparisons are over the values exactly as stored in the CSV. The
boundaries above are inclusive on both ends — `lr == 1e-5` is eligible,
`lr == 1e-3` is eligible, `dropout == 0.1` is eligible, etc.

## Selection rule

From the eligible runs, select the **top 20 by `val_acc` descending**.
If two eligible runs have the same `val_acc`, break ties by `run_id`
ascending (lexicographic).

You can assume there are at least 20 eligible runs.

## Output format

Write `output/selected.csv` with **exactly these columns, in this order**:

```
run_id,val_acc
```

- One row per selected run. Exactly **20 data rows** plus the header.
- `run_id` is the row's `run_id` from the input file, verbatim.
- `val_acc` is the run's `val_acc` from the input file. Reproduce the
  value with enough precision that it matches the source within 0.001
  — writing the value verbatim from the CSV (e.g. `0.942069`) is the
  simplest way to be safe.
- Sort the output rows by `val_acc` descending. Where `val_acc` ties,
  sort by `run_id` ascending. The grader checks this order.
- Standard CSV with a header row matching the column list above. UTF-8.
  Trailing newline at end of file.

## Scoring

Your output is scored by the F1 score of your selected `run_id` set
against the reference top-20 — perfect selection is `F1 = 1.0`,
swapping one of the top-20 for an eligible run just below the cutoff
costs about 0.05. Sort order and val_acc-vs-source agreement are
required for any non-zero score.
