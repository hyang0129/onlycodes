# Signup Funnel Conversion Report

Product is asking for a weekly funnel report: how many users who signed up
last week made it through each subsequent step (verify email → onboarding
complete → first action → subscribe).

You are given a user event log at `workspace/events.jsonl`. Each line:

```json
{"user_id": "u_000123", "event": "signup", "ts": 1702848000.5}
```

Events of interest (in intended funnel order):

1. `signup`
2. `verify_email`
3. `onboarding_complete`
4. `first_action`
5. `subscribe`

Other event names may appear (`heartbeat`, `page_view`, `logout`, etc.) — ignore
them.

## Task

For each user who emitted a `signup` event in the input window, determine the
**deepest funnel step they reached, with events in the correct order**. A user
"reaches" step `k` only if they emitted each of steps `1..k` in the correct
chronological order — that is, the timestamp of step `k` must be strictly
greater than the timestamp of step `k-1` for that same user.

Only the **first** occurrence of each event per user counts. If a user's first
`first_action` predates their first `onboarding_complete`, they did NOT reach
`first_action` (the funnel was broken).

Then compute the funnel report and write it to `output/funnel.json`.

## Output format

`output/funnel.json` — a single JSON object with exactly these keys:

```json
{
  "total_signups": <int>,
  "steps": [
    {"step": "signup",               "reached": <int>, "rate_from_prev": 1.0},
    {"step": "verify_email",         "reached": <int>, "rate_from_prev": <float>},
    {"step": "onboarding_complete",  "reached": <int>, "rate_from_prev": <float>},
    {"step": "first_action",         "reached": <int>, "rate_from_prev": <float>},
    {"step": "subscribe",            "reached": <int>, "rate_from_prev": <float>}
  ]
}
```

Rules:

- `total_signups` = number of distinct users with a `signup` event (this equals
  `reached` for step `signup`).
- `steps` MUST be in the funnel order shown above (exactly 5 entries, exact
  step names).
- `reached` = number of distinct users who reached this step or deeper under
  the in-order rule above.
- `rate_from_prev` = `reached / previous_step.reached`, rounded to **4 decimal
  places**. For the `signup` step itself, emit `1.0`. If the previous step has
  `reached == 0`, emit `0.0` for this step (avoid div-by-zero).
- Extra keys anywhere will fail the grader.

## Optional public verifier

`workspace/verify.py` exposes `verify(artifact_path: Path)` which checks the
shape of the output (required keys, types, step order, monotonicity). It does
NOT check correctness.

## Notes

- ~20,000 events, ~2,000 unique users.
- No network access required. Standard library + pandas/numpy/scipy/sklearn
  are available.
- Extra keys in the object or in `steps` entries will fail the grader.
