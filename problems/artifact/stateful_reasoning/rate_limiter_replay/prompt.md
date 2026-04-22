# Task: Replay Sliding-Window Rate Limiter

You are replaying API request events to determine which requests a
sliding-window rate limiter would have accepted vs rejected.

Input: `requests.jsonl` — one JSON object per line, in order by `ts`:

```json
{"request_id": "req_000001", "ts": 1700000000, "user_id": "u042",
 "tier": "free"}
```

- `ts` is integer unix seconds, weakly increasing (ties allowed; order within
  a tie must be preserved — use file order).
- `tier` is one of `"free"`, `"pro"`, `"enterprise"`.

## Policy

Per-user sliding-window quotas (count of *accepted* requests in the trailing
60 seconds strictly preceding or equal to the current `ts` must not exceed
the tier's allowance):

| tier | requests per 60s window |
|---|---|
| free | 5 |
| pro | 20 |
| enterprise | 100 |

- The window is `[ts - 59, ts]` inclusive (a 60-second span).
- Only *accepted* requests count toward the window; rejected ones do not.
- If a request would be the `(N+1)`-th accepted request in the window for
  that user at that `ts` (where `N` is the tier limit), reject it.

A user's tier may change across events (they can upgrade/downgrade between
requests). Always use the tier on the *current* request to decide.

## Output

Write `output/decisions.jsonl` — one JSON object per input line, **in the
same order**:

```json
{"request_id": "req_000001", "decision": "accepted"}
{"request_id": "req_000002", "decision": "rejected", "reason": "rate_limited"}
```

- `decision`: `"accepted"` or `"rejected"`.
- `reason`: required on rejected, must be the literal string `"rate_limited"`.
  Omit on accepted.
