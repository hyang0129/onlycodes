# p95 Latency per Endpoint

You are given an HTTP access log at `workspace/access.jsonl` — one JSON object per line.
Each record has at least these fields:

- `ts` — request timestamp (float, seconds since epoch; opaque, do not sort-depend on it)
- `endpoint` — request path, e.g. `/api/v2/users`, `/health`, `/healthz/ready`
- `latency_ms` — request latency in milliseconds (float ≥ 0)
- `status` — HTTP status code (int)

## Task

Compute the **p95 latency per endpoint**, then write the result to `output/p95.jsonl`.

- Exclude **all requests whose endpoint begins with `/health`** (e.g. `/health`,
  `/healthz`, `/health/live`, `/healthz/ready`). These are infra probes and
  must not contribute to the output — do not include them as rows.
- Include every other endpoint that has at least one request in the log.
- Use the **nearest-rank** p95 definition: for an endpoint with sorted latencies
  `l[0] ≤ l[1] ≤ ... ≤ l[n-1]`, the p95 is `l[k]` where `k = ceil(0.95 * n) - 1`
  (clamped to `[0, n-1]`). For `n == 1` this is the single value.

## Output format

`output/p95.jsonl` — one JSON object per line, each with exactly these keys:

```json
{"endpoint": "<path>", "p95_ms": <float>, "count": <int>}
```

- `endpoint`: the endpoint path string, exactly as it appears in the input.
- `p95_ms`: the p95 latency in milliseconds, as a number (float OK). Rounding to
  3 decimal places is acceptable; the grader uses a small tolerance.
- `count`: the number of requests for that endpoint in the input (excluding
  `/health*` exclusion — but that rule is a row-filter, not a counting modifier:
  if an endpoint is not `/health*`, its `count` is the number of its own rows).

The output rows may be in any order. Each non-excluded endpoint must appear
**exactly once** — duplicates will fail the grader.

## Optional public verifier

`workspace/verify.py` exposes `verify(artifact_path: Path)` which checks the
**shape** of your output (parseability, required keys, types). It does NOT check
correctness — passing `verify()` does not mean your p95 values are right. Using
it is optional.

## Notes

- The log fits in memory (~10k rows). Streaming is fine but not required.
- No network access is required or permitted.
- Write exactly the keys above. Extra keys will fail the grader.
