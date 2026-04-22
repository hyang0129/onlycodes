# Sessionize Page Events

The web analytics team wants a per-session rollup of user activity. We define
a **session** as a run of events for one user with no more than **30 minutes
(1800 seconds) of inactivity** between consecutive events; a gap strictly
greater than 1800s starts a new session.

You are given a page event log at `workspace/pageviews.jsonl`. One line per
event:

```json
{"user_id": "u_000123", "page": "/catalog/items", "ts": 1702848000.0, "duration_ms": 3400}
```

- `user_id`: string.
- `page`: string URL path (always starts with `/`).
- `ts`: float, seconds since epoch.
- `duration_ms`: int ≥ 0, how long the page was active.

## Task

For each `(user_id, session_idx)` pair, produce one row in
`output/sessions.jsonl`. `session_idx` is 0-based and monotonically
increasing **per user** in chronological order of that user's sessions
(i.e. the user's earliest session is idx 0, next is 1, and so on).

Row schema — exactly these keys:

```json
{
  "user_id": "<id>",
  "session_idx": <int>,
  "start_ts": <float>,
  "end_ts": <float>,
  "event_count": <int>,
  "total_duration_ms": <int>,
  "unique_pages": <int>
}
```

- `start_ts`: the smallest `ts` in the session, rounded to 3 decimals.
- `end_ts`: the largest `ts` in the session, rounded to 3 decimals. (A
  single-event session has `start_ts == end_ts`.)
- `event_count`: number of events in the session (≥ 1).
- `total_duration_ms`: sum of `duration_ms` across events in the session.
- `unique_pages`: number of distinct `page` values in the session.

Emit one row per session. Rows may be in any order — the grader checks by
`(user_id, session_idx)`.

## Optional public verifier

`workspace/verify.py` exposes `verify(artifact_path: Path)` which checks the
shape of the output. It does NOT check correctness.

## Notes

- ~30,000 events across ~1,500 users, spanning ~7 days.
- For each user, events are NOT pre-sorted in the input.
- Exact gap of 1800s is still the **same** session (strictly greater starts
  a new one).
- Extra keys in output rows will fail the grader.
