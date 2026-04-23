"""Hidden grader for enumeration__integer_partitions_15.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    Every integer partition of 15, represented as a non-increasing tuple of
    positive integers, must appear exactly once in output/partitions.jsonl.
    p(15) = 176.

Determinism: pure enumeration.
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


OUTPUT_REL = "output/partitions.jsonl"
N = 15


def _all_partitions(n: int) -> set[tuple]:
    result: set[tuple] = set()

    def rec(remaining: int, max_part: int, current: list[int]) -> None:
        if remaining == 0:
            result.add(tuple(current))
            return
        for k in range(min(remaining, max_part), 0, -1):
            current.append(k)
            rec(remaining - k, k, current)
            current.pop()

    rec(n, n, [])
    return result


def _parse_partition(obj, n: int) -> tuple | None:
    if not isinstance(obj, list) or not obj:
        return None
    if not all(isinstance(v, int) and v > 0 for v in obj):
        return None
    if sum(obj) != n:
        return None
    if obj != sorted(obj, reverse=True):
        return None
    return tuple(obj)


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    output_path = scratch_dir / OUTPUT_REL

    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    raw = output_path.read_text()
    if not raw.strip():
        return GradeResult(False, 0.0, "output artifact is empty")

    agent_parts: list[tuple] = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            return GradeResult(False, 0.0, f"line {lineno}: JSON parse error: {exc.msg}")
        p = _parse_partition(obj, N)
        if p is None:
            return GradeResult(
                False, 0.0,
                f"line {lineno}: not a valid non-increasing partition of {N}: {obj!r}",
            )
        agent_parts.append(p)

    seen: set[tuple] = set()
    dupes: list[tuple] = []
    for p in agent_parts:
        if p in seen:
            dupes.append(p)
        seen.add(p)
    if dupes:
        return GradeResult(False, 0.0, f"{len(dupes)} duplicate partition(s)")

    reference = _all_partitions(N)
    agent_set = set(agent_parts)
    missing = reference - agent_set
    extra = agent_set - reference  # shouldn't happen since parse is strict

    if missing or extra:
        parts = []
        if missing:
            parts.append(f"missing {len(missing)} partition(s)")
        if extra:
            parts.append(f"{len(extra)} unexpected entry(ies)")
        return GradeResult(
            False,
            round(len(agent_set & reference) / len(reference), 4),
            "; ".join(parts),
        )

    return GradeResult(True, 1.0, f"all {len(reference)} partitions of {N} enumerated")
