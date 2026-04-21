# Task: Identify Top-3 Latency Regressions

You are given 48 hourly API metric files covering two consecutive days:

- **Yesterday**: `metrics_2024-01-14_00.jsonl` … `metrics_2024-01-14_23.jsonl`
- **Today**: `metrics_2024-01-15_00.jsonl` … `metrics_2024-01-15_23.jsonl`

Each file is JSONL. Every line is a single request record:

```json
{"endpoint": "/api/example", "latency_ms": 123.456}
```

## Your goal

For each endpoint, compute the **day-over-day p95 latency regression**:

```
regression_score = p95(today_latencies) - p95(yesterday_latencies)
```

where p95 is the **nearest-rank p95**: sort all latency values for that endpoint
across all 24 hourly files for the given day, then return the value at index
`ceil(0.95 × N) − 1` (0-indexed, clamped to [0, N−1]).

Identify the **top-3 endpoints** with the largest regression_score (highest positive
day-over-day increase). Ties broken by endpoint string, ascending lexicographic order.

## Output

Write `output/regressions.jsonl` (relative to your working directory) with
**exactly 3 lines**, one JSON object per line, in **descending order of regression_score**:

```json
{"endpoint": "/api/example", "regression_score": 123.456}
```

- `endpoint`: exact endpoint string (e.g. `/api/payments`)
- `regression_score`: the regression value in milliseconds, as a float rounded to
  3 decimal places

## Verification

Run `python verify.py` to check your output has the correct shape before submitting.
