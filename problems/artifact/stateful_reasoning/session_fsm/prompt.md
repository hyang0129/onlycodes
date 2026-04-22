# Task: Reconstruct Session Final Status from Event Stream

Our backend emits session lifecycle events to `session_events.jsonl`.
Each event has:

- `ts`: integer unix seconds (strictly increasing across the file)
- `session_id`: string
- `event`: one of `"login"`, `"activity"`, `"logout"`

## Session state machine

Every session goes through this FSM:

```
(none) --login--> active --activity--> active --logout--> closed
                    \                             /
                     ----- (30-min idle) -----> expired
```

Rules:

1. A `login` event creates a session in `active` state. If a `login` fires
   for a `session_id` that is already `active`, treat it as a protocol error
   and mark that session `corrupted` — no further events for that session
   change its state.
2. `activity` extends the session. Every activity event updates
   `last_activity_ts` to that event's `ts`. An `activity` on a session
   that is `closed`, `expired`, or `corrupted` is ignored. An `activity`
   on a `session_id` that has never been `login`ed is ignored.
3. `logout` transitions `active` → `closed`. A `logout` on any session
   that is not currently `active` is ignored.
4. **Idle expiration:** before applying any event to a session, check if
   more than 1800 seconds (30 minutes) have elapsed since that session's
   `last_activity_ts`. If so, expire the session (`active` → `expired`)
   with `expired_at_ts = last_activity_ts + 1800`. Then apply the new event
   per the rules above (which may be a fresh `login` creating a new active
   session for the same id — that is allowed, it does not "corrupt").

## Output

Write `output/sessions.json` — a JSON object mapping each `session_id` that
appeared in at least one event to an object:

```json
{
  "sess_001": {
    "final_state": "closed",
    "login_count": 2,
    "activity_count": 5,
    "duration_s": 1240
  }
}
```

- `final_state` — one of `active`, `closed`, `expired`, `corrupted`
- `login_count` — number of `login` events observed for this id (including a
  login after an expire — but NOT counting the second login that caused
  corruption; corrupted sessions still count their first login)
- `activity_count` — number of activity events counted (ignored ones do not count)
- `duration_s` — integer seconds from the first login's `ts` to the
  terminating event's `ts` (logout for closed, `last_activity_ts + 1800`
  for expired, last processed event for corrupted, last event for active)
