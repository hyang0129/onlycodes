# Task: Reconstruct Final Feature-Flag State

Our platform team logs every feature-flag toggle to a JSONL stream. We need
to know the final state of every flag after all events have been processed,
plus the number of times each flag was flipped.

The workspace contains `flag_events.jsonl` — one JSON object per line, in
chronological order:

```json
{"flag": "checkout.v2", "action": "enable"}
{"flag": "checkout.v2", "action": "disable"}
{"flag": "search.fuzzy", "action": "enable"}
```

## Semantics

- Every flag starts implicitly `disabled`.
- `action: "enable"` sets the flag to `enabled` (idempotent — enabling an already-enabled flag counts as a toggle event for `toggle_count` purposes ONLY if the state actually changed; see below).
- `action: "disable"` sets the flag to `disabled` (idempotent, same rule).
- `toggle_count` = the number of events that CHANGED the flag's state.
  An `enable` event on an already-enabled flag does not increment the counter.

## Output

Write `output/final_flags.json`. It must be a JSON object keyed by flag name.
Each value is an object with `enabled` (boolean) and `toggle_count` (integer).
Include every flag that appeared in at least one event.

```json
{
  "checkout.v2":  {"enabled": false, "toggle_count": 2},
  "search.fuzzy": {"enabled": true,  "toggle_count": 1}
}
```
