# Task: Minimum Makespan Scheduling

You are given a set of jobs and a fixed number of machines. Each job has a duration (in integer time units). Jobs cannot be split; each job runs on exactly one machine. All machines start at time 0 and run jobs sequentially.

**Your goal**: assign every job to a machine to **minimize the makespan** (the total completion time, i.e. the maximum load across all machines).

## Input

Read `jobs.json` (in your working directory):

```json
{
  "num_machines": 3,
  "job_durations": [9, 6, 8, 25, 26, 16, 6, 9, 13, 22]
}
```

- `num_machines`: how many machines are available
- `job_durations`: list of N job durations (indices 0 … N−1)

## Output

Write `output/schedule.json` with a JSON object containing at minimum:

```json
{
  "makespan": <integer>,
  "assignment": [[job_ids_on_machine_0], [job_ids_on_machine_1], [job_ids_on_machine_2]]
}
```

- `makespan`: the maximum load across all machines for your assignment
- `assignment`: (optional but recommended) a list of `num_machines` lists, each containing the 0-indexed job IDs assigned to that machine — every job ID must appear exactly once

## Requirements

- The makespan **must be globally optimal** (minimum possible).
- With N=10 jobs and M=3 machines, there are at most 3^10 = 59,049 possible assignments — an exhaustive search is tractable.

## Verification

Run `python verify.py` to check that your output has the correct schema before submitting.
