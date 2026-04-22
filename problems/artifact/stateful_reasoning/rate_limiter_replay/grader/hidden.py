"""Hidden grader for stateful_reasoning__rate_limiter_replay.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Replay the same rate-limiter policy (per-user sliding-window count of
accepted requests in [ts-59, ts]) and compare per-request decisions to
the agent's decisions.jsonl, in order. Deterministic, stdlib-only.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


OUTPUT_REL = "output/decisions.jsonl"
REQ_REL = "requests.jsonl"
WINDOW_SECONDS = 60
LIMITS = {"free": 5, "pro": 20, "enterprise": 100}


def _replay(req_path: Path) -> list[dict]:
    decisions: list[dict] = []
    # Per-user deque of accepted timestamps within the trailing window
    accepted_ts: dict[str, deque] = {}

    with open(req_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            rid = e["request_id"]
            ts = int(e["ts"])
            user = e["user_id"]
            tier = e["tier"]
            limit = LIMITS[tier]

            dq = accepted_ts.setdefault(user, deque())
            # Evict ts < (ts - 59)  i.e. keep those >= ts - 59
            cutoff = ts - (WINDOW_SECONDS - 1)
            while dq and dq[0] < cutoff:
                dq.popleft()

            if len(dq) >= limit:
                decisions.append({"request_id": rid,
                                   "decision": "rejected",
                                   "reason": "rate_limited"})
            else:
                dq.append(ts)
                decisions.append({"request_id": rid, "decision": "accepted"})
    return decisions


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    output_path = scratch_dir / OUTPUT_REL
    req_path = scratch_dir / REQ_REL

    if not req_path.is_file():
        return GradeResult(False, 0.0, "requests.jsonl not found")
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        ref = _replay(req_path)
    except Exception as exc:
        return GradeResult(False, 0.0, f"grader replay failed: {exc}")

    agent: list[dict] = []
    raw = output_path.read_text()
    for ln, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            return GradeResult(False, 0.0, f"line {ln}: JSON parse error: {exc.msg}")
        if not isinstance(obj, dict):
            return GradeResult(False, 0.0, f"line {ln}: expected JSON object")
        agent.append(obj)

    if len(agent) != len(ref):
        return GradeResult(False,
                           round(0.0, 4),
                           f"output has {len(agent)} lines, expected {len(ref)}")

    mismatches = 0
    sample = []
    for i, (a, r) in enumerate(zip(agent, ref)):
        if a.get("request_id") != r["request_id"]:
            mismatches += 1
            if len(sample) < 3:
                sample.append(f"line {i+1}: request_id {a.get('request_id')!r} vs ref {r['request_id']!r}")
            continue
        if a.get("decision") != r["decision"]:
            mismatches += 1
            if len(sample) < 3:
                sample.append(f"{r['request_id']}: decision {a.get('decision')!r} vs ref {r['decision']!r}")
            continue
        if r["decision"] == "rejected":
            if a.get("reason") != r["reason"]:
                mismatches += 1
                if len(sample) < 3:
                    sample.append(f"{r['request_id']}: reason {a.get('reason')!r} vs ref {r['reason']!r}")

    if mismatches:
        correct = len(ref) - mismatches
        score = round(correct / max(len(ref), 1), 4)
        return GradeResult(False, score, f"{mismatches}/{len(ref)} decisions wrong; e.g. {sample}")

    return GradeResult(True, 1.0, f"all {len(ref)} decisions match")
