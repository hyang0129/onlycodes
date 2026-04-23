"""Hidden grader for enumeration__nqueens_7.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    Every distinct 7-queens placement (n=7, no symmetry reduction) must appear
    exactly once in output/solutions.jsonl. There are 40 such placements.

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


OUTPUT_REL = "output/solutions.jsonl"
N = 7


def _enumerate_solutions(n: int) -> set[tuple]:
    result: set[tuple] = set()

    def backtrack(row: int, cols: set[int], d1: set[int], d2: set[int], current: list[int]) -> None:
        if row == n:
            result.add(tuple(current))
            return
        for c in range(n):
            if c in cols or (row - c) in d1 or (row + c) in d2:
                continue
            current.append(c)
            cols.add(c); d1.add(row - c); d2.add(row + c)
            backtrack(row + 1, cols, d1, d2, current)
            cols.remove(c); d1.remove(row - c); d2.remove(row + c)
            current.pop()

    backtrack(0, set(), set(), set(), [])
    return result


def _parse_solution(obj) -> tuple | None:
    if not isinstance(obj, list) or len(obj) != N:
        return None
    if not all(isinstance(v, int) for v in obj):
        return None
    if sorted(obj) != list(range(N)):
        return None
    # Check diagonal constraint
    for i in range(N):
        for j in range(i + 1, N):
            if abs(obj[i] - obj[j]) == j - i:
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

    agent_sols: list[tuple] = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            return GradeResult(False, 0.0, f"line {lineno}: JSON parse error: {exc.msg}")
        sol = _parse_solution(obj)
        if sol is None:
            return GradeResult(
                False, 0.0,
                f"line {lineno}: not a valid 7-queens solution: {obj!r}",
            )
        agent_sols.append(sol)

    seen: set[tuple] = set()
    dupes: list[tuple] = []
    for s in agent_sols:
        if s in seen:
            dupes.append(s)
        seen.add(s)
    if dupes:
        return GradeResult(False, 0.0, f"{len(dupes)} duplicate solution(s)")

    reference = _enumerate_solutions(N)
    agent_set = set(agent_sols)
    missing = reference - agent_set
    extra = agent_set - reference

    if missing or extra:
        parts = []
        if missing:
            parts.append(f"missing {len(missing)} solution(s)")
        if extra:
            parts.append(f"{len(extra)} invalid placement(s)")
        return GradeResult(
            False,
            round(len(agent_set & reference) / len(reference), 4),
            "; ".join(parts),
        )

    return GradeResult(True, 1.0, f"all {len(reference)} 7-queens solutions enumerated")
