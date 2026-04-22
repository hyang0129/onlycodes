"""Hidden grader for stateful_reasoning__counter_replay.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Replay the events in ``events.jsonl`` independently and compare the final
counter map to the agent's ``output/counters.json``.

Determinism: pure stdlib, no randomness.
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


OUTPUT_REL = "output/counters.json"
EVENTS_REL = "events.jsonl"


def _replay(events_path: Path) -> dict[str, int]:
    counters: dict[str, int] = {}
    with open(events_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            evt = json.loads(line)
            name = evt["name"]
            op = evt["op"]
            if op == "inc":
                counters[name] = counters.get(name, 0) + int(evt["delta"])
            elif op == "dec":
                counters[name] = counters.get(name, 0) - int(evt["delta"])
            elif op == "reset":
                counters[name] = 0
            else:
                raise ValueError(f"unknown op: {op}")
    return counters


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    output_path = scratch_dir / OUTPUT_REL
    events_path = scratch_dir / EVENTS_REL

    if not events_path.is_file():
        return GradeResult(False, 0.0, "events.jsonl not found in scratch dir")
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        raw = output_path.read_text()
        agent = json.loads(raw)
    except json.JSONDecodeError as exc:
        return GradeResult(False, 0.0, f"output is not valid JSON: {exc}")

    if not isinstance(agent, dict):
        return GradeResult(False, 0.0, f"output must be a JSON object, got {type(agent).__name__}")

    for k, v in agent.items():
        if not isinstance(k, str):
            return GradeResult(False, 0.0, f"counter key must be string: {k!r}")
        if not isinstance(v, int) or isinstance(v, bool):
            return GradeResult(False, 0.0, f"counter value must be integer for {k!r}: {v!r}")

    try:
        reference = _replay(events_path)
    except Exception as exc:
        return GradeResult(False, 0.0, f"grader failed to replay events: {exc}")

    agent_keys = set(agent.keys())
    ref_keys = set(reference.keys())

    missing = ref_keys - agent_keys
    extra = agent_keys - ref_keys
    wrong = {k: (agent[k], reference[k]) for k in agent_keys & ref_keys if agent[k] != reference[k]}

    if missing or extra or wrong:
        parts = []
        if missing:
            parts.append(f"missing {len(missing)}: {sorted(missing)[:5]}")
        if extra:
            parts.append(f"extra {len(extra)}: {sorted(extra)[:5]}")
        if wrong:
            sample = list(wrong.items())[:3]
            parts.append(f"{len(wrong)} wrong values, e.g. {sample}")
        correct = len(ref_keys & agent_keys) - len(wrong)
        score = round(correct / max(len(ref_keys), 1), 4)
        return GradeResult(False, score, "; ".join(parts))

    return GradeResult(True, 1.0, f"all {len(reference)} counter values correct")
