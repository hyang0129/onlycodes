"""Hidden grader for stateful_reasoning__feature_flag_timeline.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Replay the flag_events.jsonl stream and compare the final state map to the
agent's output. Deterministic, stdlib-only.
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


OUTPUT_REL = "output/final_flags.json"
EVENTS_REL = "flag_events.jsonl"


def _replay(events_path: Path) -> dict[str, dict]:
    state: dict[str, bool] = {}
    toggles: dict[str, int] = {}
    with open(events_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            evt = json.loads(line)
            flag = evt["flag"]
            action = evt["action"]
            new_val = True if action == "enable" else False if action == "disable" else None
            if new_val is None:
                raise ValueError(f"unknown action: {action}")
            prev = state.get(flag, False)
            if flag not in state:
                toggles[flag] = 0
                state[flag] = False
            if prev != new_val:
                toggles[flag] = toggles.get(flag, 0) + 1
                state[flag] = new_val
    return {k: {"enabled": state[k], "toggle_count": toggles[k]} for k in state}


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    output_path = scratch_dir / OUTPUT_REL
    events_path = scratch_dir / EVENTS_REL

    if not events_path.is_file():
        return GradeResult(False, 0.0, "flag_events.jsonl not found")
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        agent = json.loads(output_path.read_text())
    except json.JSONDecodeError as exc:
        return GradeResult(False, 0.0, f"output is not valid JSON: {exc}")

    if not isinstance(agent, dict):
        return GradeResult(False, 0.0, f"output must be a JSON object, got {type(agent).__name__}")

    for k, v in agent.items():
        if not isinstance(v, dict):
            return GradeResult(False, 0.0, f"flag {k!r}: value must be object")
        if "enabled" not in v or "toggle_count" not in v:
            return GradeResult(False, 0.0, f"flag {k!r}: missing 'enabled' or 'toggle_count'")
        if not isinstance(v["enabled"], bool):
            return GradeResult(False, 0.0, f"flag {k!r}: 'enabled' must be bool")
        if not isinstance(v["toggle_count"], int) or isinstance(v["toggle_count"], bool):
            return GradeResult(False, 0.0, f"flag {k!r}: 'toggle_count' must be int")

    try:
        reference = _replay(events_path)
    except Exception as exc:
        return GradeResult(False, 0.0, f"grader replay failed: {exc}")

    agent_keys = set(agent.keys())
    ref_keys = set(reference.keys())

    missing = ref_keys - agent_keys
    extra = agent_keys - ref_keys

    wrong: list[str] = []
    for k in agent_keys & ref_keys:
        if agent[k].get("enabled") != reference[k]["enabled"]:
            wrong.append(f"{k}: enabled {agent[k].get('enabled')} vs ref {reference[k]['enabled']}")
        elif agent[k].get("toggle_count") != reference[k]["toggle_count"]:
            wrong.append(f"{k}: toggle_count {agent[k].get('toggle_count')} vs ref {reference[k]['toggle_count']}")

    if missing or extra or wrong:
        parts = []
        if missing:
            parts.append(f"missing {len(missing)}: {sorted(missing)[:5]}")
        if extra:
            parts.append(f"extra {len(extra)}: {sorted(extra)[:5]}")
        if wrong:
            parts.append(f"{len(wrong)} wrong: {wrong[:3]}")
        correct = len(ref_keys & agent_keys) - len(wrong)
        score = round(correct / max(len(ref_keys), 1), 4)
        return GradeResult(False, score, "; ".join(parts))

    return GradeResult(True, 1.0, f"all {len(reference)} flag states match")
