# Task: Replay Counter Events

Our telemetry team captured a stream of counter-update events for a set of
named metrics. We need to replay the events in order and report the final
value for every metric.

The workspace contains `events.jsonl` — one JSON object per line, in
chronological order. Each event has these fields:

```json
{"op": "inc",   "name": "requests.total", "delta": 3}
{"op": "dec",   "name": "queue.depth",    "delta": 1}
{"op": "reset", "name": "errors.5xx"}
```

## Semantics

- Every counter starts at `0`.
- `op: "inc"` adds `delta` (a non-negative integer) to the named counter.
- `op: "dec"` subtracts `delta`. Counters may go negative — do not clamp.
- `op: "reset"` sets the named counter back to `0` (no `delta` field).
- A counter exists in the output iff it appears in at least one event.

## Output

Write `output/counters.json` — a single JSON object mapping each counter name
to its final integer value, sorted by name (alphabetical) so diffs are stable:

```json
{
  "cache.hits": 42,
  "errors.5xx": 0,
  "queue.depth": -1,
  "requests.total": 150
}
```

All values must be JSON numbers (integers). Do not include counters that
never appeared in the event stream.
