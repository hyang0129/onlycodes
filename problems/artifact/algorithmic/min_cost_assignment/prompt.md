# Task: Minimum Cost Assignment

You are given a square cost matrix where `cost_matrix[i][j]` is the cost of assigning worker `i` to task `j`. Find the **minimum cost perfect assignment** — assign each worker to exactly one task and each task to exactly one worker, minimizing total cost.

## Input

Read `cost_matrix.json` (in your working directory):

```json
{
  "num_workers": 20,
  "num_tasks": 20,
  "cost_matrix": [[...], ...]
}
```

All costs are positive integers. The matrix is 20×20.

## Output

Write `output/assignment.json`:

```json
{
  "assignment": [task_for_worker_0, task_for_worker_1, ..., task_for_worker_19],
  "total_cost": <integer>
}
```

- `assignment`: list of 20 integers — `assignment[i]` is the 0-indexed task assigned to worker `i`
- Every task must appear exactly once (perfect matching)
- `total_cost`: the sum of `cost_matrix[i][assignment[i]]` for all `i`

## Requirements

- The total cost **must be globally optimal** (minimum possible).
- The Hungarian algorithm (Kuhn–Munkres) solves this exactly in O(n³) time. Implementations are available in `scipy.optimize.linear_sum_assignment` or can be written from scratch.

## Verification

Run `python verify.py` to check that your output has the correct schema before submitting.
