"""Hidden grader for enumeration__subset_sum_count.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    Enumerate every subset of indices into amounts[] summing to target,
    compare with the agent's output.

Reads workspace/amounts.json (materialized into scratch_dir) as the canonical
input. Determinism: pure enumeration.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


OUTPUT_REL = "output/subsets.jsonl"
INPUT_REL = "amounts.json"


def _ground_truth(amounts: list[int], target: int) -> set[tuple]:
    n = len(amounts)
    result: set[tuple] = set()
    # r=0 allowed if target==0
    start = 0 if target == 0 else 1
    for r in range(start, n + 1):
        for combo in itertools.combinations(range(n), r):
            if sum(amounts[i] for i in combo) == target:
                result.add(tuple(combo))
    return result


def _parse_subset(obj, n: int) -> tuple | None:
    if not isinstance(obj, list):
        return None
    if not all(isinstance(v, int) for v in obj):
        return None
    if any(v < 0 or v >= n for v in obj):
        return None
    if obj != sorted(obj):
        return None
    if len(set(obj)) != len(obj):
        return None
    return tuple(obj)


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    output_path = scratch_dir / OUTPUT_REL
    input_path = scratch_dir / INPUT_REL

    if not input_path.is_file():
        return GradeResult(False, 0.0, f"workspace input missing: {INPUT_REL}")
    try:
        data = json.loads(input_path.read_text())
        amounts = data["amounts"]
        target = data["target"]
        if not isinstance(amounts, list) or not all(isinstance(v, int) for v in amounts):
            raise ValueError("amounts must be list[int]")
        if not isinstance(target, int):
            raise ValueError("target must be int")
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        return GradeResult(False, 0.0, f"malformed workspace input: {exc}")

    n = len(amounts)

    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    raw = output_path.read_text()
    if not raw.strip():
        return GradeResult(False, 0.0, "output artifact is empty")

    agent_subsets: list[tuple] = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            return GradeResult(False, 0.0, f"line {lineno}: JSON parse error: {exc.msg}")
        sub = _parse_subset(obj, n)
        if sub is None:
            return GradeResult(
                False, 0.0,
                f"line {lineno}: expected sorted list of distinct indices in [0,{n}), got {obj!r}",
            )
        # Check that it sums to target
        if sum(amounts[i] for i in sub) != target:
            return GradeResult(
                False, 0.0,
                f"line {lineno}: subset {list(sub)} sums to "
                f"{sum(amounts[i] for i in sub)}, not target {target}",
            )
        agent_subsets.append(sub)

    seen: set[tuple] = set()
    dupes: list[tuple] = []
    for s in agent_subsets:
        if s in seen:
            dupes.append(s)
        seen.add(s)
    if dupes:
        return GradeResult(False, 0.0, f"{len(dupes)} duplicate subset(s) in output")

    reference = _ground_truth(amounts, target)
    agent_set = set(agent_subsets)
    missing = reference - agent_set
    extra = agent_set - reference  # should be empty since we filtered by sum

    if missing or extra:
        parts = []
        if missing:
            parts.append(f"missing {len(missing)} subset(s)")
        if extra:
            parts.append(f"{len(extra)} unexpected subset(s)")
        return GradeResult(
            False,
            round(len(agent_set & reference) / max(len(reference), 1), 4),
            "; ".join(parts),
        )

    return GradeResult(
        True, 1.0,
        f"all {len(reference)} subsets summing to {target} enumerated",
    )
