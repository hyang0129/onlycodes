"""Hidden grader for data_processing__funnel_conversion.

Contract: ``grade(scratch_dir: Path) -> GradeResult``.

Correctness criterion:

    Recompute the funnel from ``events.jsonl`` using:
      - per (user, event) pick the earliest ts,
      - a user "reaches" step k iff ts(step_i) < ts(step_{i+1}) for all i < k
        using each user's earliest per-event ts,
      - steps must be: signup, verify_email, onboarding_complete,
        first_action, subscribe.

    Agent's output must match: total_signups exact, each step reached exact,
    rate_from_prev within 1e-4 absolute tolerance (rounded to 4 decimals per
    prompt).

Determinism: pure function of scratch_dir.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


INPUT_REL = "events.jsonl"
OUTPUT_REL = "output/funnel.json"

FUNNEL = ["signup", "verify_email", "onboarding_complete", "first_action", "subscribe"]
RATE_ABS_TOL = 1e-4

TOP_KEYS = frozenset({"total_signups", "steps"})
STEP_KEYS = frozenset({"step", "reached", "rate_from_prev"})


def _compute_truth(events_path: Path) -> dict:
    earliest: dict[str, dict[str, float]] = {}  # user -> event -> first ts
    with open(events_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            uid = r["user_id"]
            ev = r["event"]
            ts = float(r["ts"])
            per_user = earliest.setdefault(uid, {})
            prior = per_user.get(ev)
            if prior is None or ts < prior:
                per_user[ev] = ts

    signup_users = {u for u, evs in earliest.items() if "signup" in evs}
    total = len(signup_users)

    reached_counts = [0] * len(FUNNEL)
    reached_counts[0] = total

    for uid in signup_users:
        evs = earliest[uid]
        last_ts = evs["signup"]
        depth = 1
        for step in FUNNEL[1:]:
            ts = evs.get(step)
            if ts is None or ts <= last_ts:
                break
            depth += 1
            last_ts = ts
        for k in range(depth):
            reached_counts[k] += 0  # signup already counted; others added below
        # Increment reached for every step from 1..depth-1 (signup already set).
        for k in range(1, depth):
            reached_counts[k] += 1

    steps_out = []
    for idx, name in enumerate(FUNNEL):
        if idx == 0:
            rate = 1.0
        else:
            prev = reached_counts[idx - 1]
            rate = 0.0 if prev == 0 else reached_counts[idx] / prev
        steps_out.append({
            "step": name,
            "reached": reached_counts[idx],
            "rate_from_prev": round(rate, 4),
        })

    return {"total_signups": total, "steps": steps_out}


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    events_path = scratch_dir / INPUT_REL
    output_path = scratch_dir / OUTPUT_REL

    if not events_path.is_file():
        return GradeResult(False, 0.0, f"input {INPUT_REL} not found")
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        raw = output_path.read_text()
        doc = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse output: {exc}")

    if not isinstance(doc, dict):
        return GradeResult(False, 0.0, "output is not a JSON object")
    keys = set(doc.keys())
    if keys != TOP_KEYS:
        missing = TOP_KEYS - keys
        extra = keys - TOP_KEYS
        bits = []
        if missing:
            bits.append(f"missing {sorted(missing)}")
        if extra:
            bits.append(f"extra {sorted(extra)}")
        return GradeResult(False, 0.0, f"top-level: {'; '.join(bits)}")

    truth = _compute_truth(events_path)

    got_total = doc["total_signups"]
    if isinstance(got_total, bool) or not isinstance(got_total, int):
        return GradeResult(False, 0.0, "total_signups must be int")
    if got_total != truth["total_signups"]:
        return GradeResult(
            False, 0.0,
            f"total_signups {got_total} != expected {truth['total_signups']}",
        )

    got_steps = doc["steps"]
    if not isinstance(got_steps, list) or len(got_steps) != 5:
        return GradeResult(False, 0.0, "steps must be a list of exactly 5 entries")

    for idx, (got, want) in enumerate(zip(got_steps, truth["steps"])):
        if not isinstance(got, dict):
            return GradeResult(False, 0.0, f"steps[{idx}] not an object")
        ks = set(got.keys())
        if ks != STEP_KEYS:
            missing = STEP_KEYS - ks
            extra = ks - STEP_KEYS
            bits = []
            if missing:
                bits.append(f"missing {sorted(missing)}")
            if extra:
                bits.append(f"extra {sorted(extra)}")
            return GradeResult(False, 0.0, f"steps[{idx}]: {'; '.join(bits)}")
        if got["step"] != want["step"]:
            return GradeResult(
                False, 0.0,
                f"steps[{idx}].step {got['step']!r} != expected {want['step']!r}",
            )
        reached = got["reached"]
        if isinstance(reached, bool) or not isinstance(reached, int):
            return GradeResult(False, 0.0, f"steps[{idx}].reached must be int")
        if reached != want["reached"]:
            return GradeResult(
                False, 0.0,
                f"steps[{idx}] ({want['step']}).reached {reached} != expected {want['reached']}",
            )
        rate = got["rate_from_prev"]
        if isinstance(rate, bool) or not isinstance(rate, (int, float)):
            return GradeResult(False, 0.0, f"steps[{idx}].rate_from_prev must be number")
        if not math.isfinite(float(rate)):
            return GradeResult(False, 0.0, f"steps[{idx}].rate_from_prev not finite")
        if abs(float(rate) - want["rate_from_prev"]) > RATE_ABS_TOL:
            return GradeResult(
                False, 0.0,
                f"steps[{idx}] ({want['step']}).rate_from_prev {rate} != "
                f"expected ~{want['rate_from_prev']}",
            )

    return GradeResult(
        True, 1.0,
        f"funnel matched: {[s['reached'] for s in truth['steps']]}",
    )
