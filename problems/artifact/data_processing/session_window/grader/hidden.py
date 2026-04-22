"""Hidden grader for data_processing__session_window.

Correctness: recompute sessions per user using a 1800s inactivity gap
(gap STRICTLY > 1800.0 starts a new session). For each session, compute
start_ts, end_ts, event_count, total_duration_ms, unique_pages. Match
against the agent's output by (user_id, session_idx).

Determinism: pure function of scratch_dir.
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


INPUT_REL = "pageviews.jsonl"
OUTPUT_REL = "output/sessions.jsonl"

GAP = 1800.0
TS_ABS_TOL = 0.01

REQUIRED = frozenset({"user_id", "session_idx", "start_ts", "end_ts",
                      "event_count", "total_duration_ms", "unique_pages"})


def _truth(events_path: Path) -> dict[tuple[str, int], dict]:
    by_user: dict[str, list[dict]] = {}
    with open(events_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            by_user.setdefault(r["user_id"], []).append(r)

    out: dict[tuple[str, int], dict] = {}
    for uid, events in by_user.items():
        events.sort(key=lambda e: float(e["ts"]))
        cur: list[dict] = []
        idx = 0
        for e in events:
            if cur and float(e["ts"]) - float(cur[-1]["ts"]) > GAP:
                out[(uid, idx)] = _summarize(uid, idx, cur)
                idx += 1
                cur = []
            cur.append(e)
        if cur:
            out[(uid, idx)] = _summarize(uid, idx, cur)
    return out


def _summarize(uid: str, idx: int, group: list[dict]) -> dict:
    start = min(float(e["ts"]) for e in group)
    end = max(float(e["ts"]) for e in group)
    total_dur = sum(int(e["duration_ms"]) for e in group)
    pages = {e["page"] for e in group}
    return {
        "user_id": uid,
        "session_idx": idx,
        "start_ts": round(start, 3),
        "end_ts": round(end, 3),
        "event_count": len(group),
        "total_duration_ms": total_dur,
        "unique_pages": len(pages),
    }


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    inp = scratch_dir / INPUT_REL
    outp = scratch_dir / OUTPUT_REL

    if not inp.is_file():
        return GradeResult(False, 0.0, f"input {INPUT_REL} not found")
    if not outp.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    truth = _truth(inp)

    seen: dict[tuple[str, int], dict] = {}
    for lineno, line in enumerate(outp.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            return GradeResult(False, 0.0, f"line {lineno}: bad JSON ({exc.msg})")
        if not isinstance(row, dict):
            return GradeResult(False, 0.0, f"line {lineno}: not an object")
        keys = set(row.keys())
        if keys != REQUIRED:
            missing = REQUIRED - keys
            extra = keys - REQUIRED
            bits = []
            if missing:
                bits.append(f"missing {sorted(missing)}")
            if extra:
                bits.append(f"extra {sorted(extra)}")
            return GradeResult(False, 0.0, f"line {lineno}: {'; '.join(bits)}")

        uid = row["user_id"]
        idx = row["session_idx"]
        if isinstance(idx, bool) or not isinstance(idx, int):
            return GradeResult(False, 0.0, f"line {lineno}: session_idx must be int")
        key = (uid, idx)
        if key in seen:
            return GradeResult(False, 0.0, f"line {lineno}: duplicate {key}")
        seen[key] = row

    truth_keys = set(truth.keys())
    got_keys = set(seen.keys())

    missing = sorted(truth_keys - got_keys)
    extra = sorted(got_keys - truth_keys)
    if missing:
        return GradeResult(False, 0.0,
                           f"missing {len(missing)} session(s): {missing[:3]}"
                           + (" ..." if len(missing) > 3 else ""))
    if extra:
        return GradeResult(False, 0.0,
                           f"{len(extra)} unexpected session(s): {extra[:3]}"
                           + (" ..." if len(extra) > 3 else ""))

    for key, want in truth.items():
        got = seen[key]
        for field in ("event_count", "total_duration_ms", "unique_pages"):
            gv = got[field]
            if isinstance(gv, bool) or not isinstance(gv, int):
                return GradeResult(False, 0.0, f"{key}: {field} not int")
            if gv != want[field]:
                return GradeResult(
                    False, 0.0,
                    f"{key}: {field} {gv} != expected {want[field]}",
                )
        for field in ("start_ts", "end_ts"):
            gv = got[field]
            if isinstance(gv, bool) or not isinstance(gv, (int, float)):
                return GradeResult(False, 0.0, f"{key}: {field} not number")
            if abs(float(gv) - want[field]) > TS_ABS_TOL:
                return GradeResult(
                    False, 0.0,
                    f"{key}: {field} {gv} != expected ~{want[field]}",
                )

    return GradeResult(True, 1.0, f"matched {len(truth)} sessions across users")
