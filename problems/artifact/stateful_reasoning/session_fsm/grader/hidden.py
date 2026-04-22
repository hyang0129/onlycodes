"""Hidden grader for stateful_reasoning__session_fsm.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Replay the session FSM described in prompt.md and compare the resulting
per-session summary to the agent's output/sessions.json. Deterministic,
stdlib-only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


OUTPUT_REL = "output/sessions.json"
EVENTS_REL = "session_events.jsonl"
IDLE_LIMIT = 1800


def _replay(events_path: Path) -> dict[str, dict]:
    # Per-session tracked fields
    state: dict[str, str] = {}  # 'active'|'closed'|'expired'|'corrupted'|'pristine'
    first_login_ts: dict[str, int] = {}
    last_event_ts: dict[str, int] = {}      # last event observed (for "active" final duration)
    last_activity_ts: dict[str, int] = {}   # last activity or login ts (for expiry calc)
    terminating_ts: dict[str, int] = {}     # ts used to compute final duration
    login_count: dict[str, int] = {}
    activity_count: dict[str, int] = {}
    seen: set[str] = set()

    def _maybe_expire(sid: str, now_ts: int) -> None:
        if state.get(sid) == "active":
            if now_ts - last_activity_ts[sid] > IDLE_LIMIT:
                state[sid] = "expired"
                terminating_ts[sid] = last_activity_ts[sid] + IDLE_LIMIT

    with open(events_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            evt = json.loads(line)
            sid = evt["session_id"]
            event = evt["event"]
            ts = int(evt["ts"])

            seen.add(sid)
            last_event_ts[sid] = ts

            # idle-expiry check before applying
            _maybe_expire(sid, ts)
            cur = state.get(sid)  # may be None (never logged in)

            if event == "login":
                if cur == "active":
                    # protocol violation -> corrupted (do not count this second login)
                    state[sid] = "corrupted"
                    terminating_ts[sid] = ts
                    continue
                # from none/closed/expired/corrupted (corrupted stays corrupted)
                if cur == "corrupted":
                    continue
                # fresh login (possibly after expire)
                state[sid] = "active"
                if sid not in first_login_ts:
                    first_login_ts[sid] = ts
                last_activity_ts[sid] = ts
                login_count[sid] = login_count.get(sid, 0) + 1
                activity_count.setdefault(sid, 0)

            elif event == "activity":
                if cur != "active":
                    continue
                last_activity_ts[sid] = ts
                activity_count[sid] = activity_count.get(sid, 0) + 1

            elif event == "logout":
                if cur != "active":
                    continue
                state[sid] = "closed"
                terminating_ts[sid] = ts

            else:
                raise ValueError(f"unknown event: {event}")

    # After stream: any still-active session that has been idle past the
    # limit at the final ts does NOT auto-expire — it stays active (we
    # only expire on a subsequent event per the spec). final_state="active"
    # duration uses last_event_ts for that session.
    result: dict[str, dict] = {}
    for sid in seen:
        if sid in state:
            final = state[sid]
        else:
            # session had only stray events (no login ever) -> omit from output
            # per spec, login_count=0 sessions that never became anything
            # still counted as "seen" but have no defined FSM state.
            # We'll include them with login_count=0 and final_state="pristine"
            # ... BUT the prompt says "appeared in at least one event".
            # For grading simplicity: if never logged in, activity_count=0,
            # login_count=0, final_state="pristine", duration_s=0.
            result[sid] = {
                "final_state": "pristine",
                "login_count": 0,
                "activity_count": 0,
                "duration_s": 0,
            }
            continue

        if final == "active":
            term = last_event_ts[sid]
        else:
            term = terminating_ts.get(sid, last_event_ts[sid])

        start = first_login_ts.get(sid, last_event_ts[sid])
        duration = max(0, term - start)

        result[sid] = {
            "final_state": final,
            "login_count": login_count.get(sid, 0),
            "activity_count": activity_count.get(sid, 0),
            "duration_s": duration,
        }

    return result


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    output_path = scratch_dir / OUTPUT_REL
    events_path = scratch_dir / EVENTS_REL

    if not events_path.is_file():
        return GradeResult(False, 0.0, "session_events.jsonl not found")
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        agent = json.loads(output_path.read_text())
    except json.JSONDecodeError as exc:
        return GradeResult(False, 0.0, f"output is not valid JSON: {exc}")

    if not isinstance(agent, dict):
        return GradeResult(False, 0.0, f"output must be a JSON object")

    try:
        reference = _replay(events_path)
    except Exception as exc:
        return GradeResult(False, 0.0, f"grader replay failed: {exc}")

    # Strip "pristine" sessions from the reference — the prompt does not
    # require them and requiring them would over-specify. Let the agent
    # optionally include them; we only grade on non-pristine sessions.
    reference = {k: v for k, v in reference.items() if v["final_state"] != "pristine"}

    required_keys = {"final_state", "login_count", "activity_count", "duration_s"}

    missing = set(reference.keys()) - set(agent.keys())
    wrong: list[str] = []
    for sid, ref_val in reference.items():
        if sid not in agent:
            continue
        av = agent[sid]
        if not isinstance(av, dict) or not required_keys.issubset(av.keys()):
            wrong.append(f"{sid}: missing fields")
            continue
        for k in required_keys:
            if av[k] != ref_val[k]:
                wrong.append(f"{sid}.{k}: {av[k]!r} vs ref {ref_val[k]!r}")
                break

    if missing or wrong:
        parts = []
        if missing:
            parts.append(f"missing {len(missing)} sessions: {sorted(missing)[:5]}")
        if wrong:
            parts.append(f"{len(wrong)} wrong: {wrong[:3]}")
        correct = len(reference) - len(missing) - len(wrong)
        score = round(correct / max(len(reference), 1), 4)
        return GradeResult(False, score, "; ".join(parts))

    return GradeResult(True, 1.0, f"all {len(reference)} non-pristine session summaries match")
