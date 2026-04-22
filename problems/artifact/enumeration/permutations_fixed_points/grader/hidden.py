"""Hidden grader for enumeration__permutations_fixed_points.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    The agent's output/perms.jsonl MUST list every permutation of [0..4] that
    has exactly 2 fixed points — no more, no fewer, no duplicates.

    Grader re-enumerates the ground-truth set and checks set equality via
    tuple canonicalization.

Determinism: pure enumeration, no randomness.
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


OUTPUT_REL = "output/perms.jsonl"
N = 5
K = 2  # required fixed-point count


def _ground_truth() -> set[tuple]:
    base = list(range(N))
    return {
        p
        for p in itertools.permutations(base)
        if sum(1 for i, v in enumerate(p) if v == i) == K
    }


def _parse_perm(obj) -> tuple | None:
    if not isinstance(obj, list) or len(obj) != N:
        return None
    if not all(isinstance(v, int) for v in obj):
        return None
    if sorted(obj) != list(range(N)):
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

    agent_perms: list[tuple] = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            return GradeResult(False, 0.0, f"line {lineno}: JSON parse error: {exc.msg}")
        perm = _parse_perm(obj)
        if perm is None:
            return GradeResult(
                False, 0.0,
                f"line {lineno}: expected permutation of 0..{N-1}, got {obj!r}",
            )
        agent_perms.append(perm)

    seen: set[tuple] = set()
    dupes: list[tuple] = []
    for p in agent_perms:
        if p in seen:
            dupes.append(p)
        seen.add(p)
    if dupes:
        return GradeResult(
            False, 0.0,
            f"{len(dupes)} duplicate permutation(s) — remove duplicates",
        )

    reference = _ground_truth()
    agent_set = set(agent_perms)
    missing = reference - agent_set
    extra = agent_set - reference

    if missing or extra:
        parts = []
        if missing:
            parts.append(f"missing {len(missing)} permutation(s)")
        if extra:
            parts.append(
                f"{len(extra)} permutation(s) in output do not have exactly {K} fixed points"
            )
        return GradeResult(
            False,
            round(len(agent_set & reference) / len(reference), 4),
            "; ".join(parts),
        )

    return GradeResult(
        True, 1.0,
        f"all {len(reference)} permutations with exactly {K} fixed points enumerated",
    )
