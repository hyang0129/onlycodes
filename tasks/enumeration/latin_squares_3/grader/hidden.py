"""Hidden grader for enumeration__latin_squares_3.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    The agent's output/latin_squares.jsonl MUST list ALL 12 distinct 3×3 Latin
    squares (symbols 1-3), no more and no fewer, with no duplicates.

    Grader re-enumerates the ground truth, converts both sets to canonical
    (frozenset of sorted tuples) form, and checks set equality.

    Duplicates → hard fail with count.
    Missing items → fail with count.
    Extra items → fail with count.

Determinism: pure enumeration, no randomness.
"""
# GRADER-SENTINEL: 8bb210a2-c805-4ef4-ab2c-af518e2c9911

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


OUTPUT_REL = "output/latin_squares.jsonl"


def _all_latin_squares_3() -> set[tuple]:
    """Enumerate all 3×3 Latin squares with symbols {1,2,3}."""
    result = set()
    for r1 in itertools.permutations([1, 2, 3]):
        for r2 in itertools.permutations([1, 2, 3]):
            for r3 in itertools.permutations([1, 2, 3]):
                sq = (r1, r2, r3)
                if all(
                    sorted(sq[row][col] for row in range(3)) == [1, 2, 3]
                    for col in range(3)
                ):
                    result.add(sq)
    return result


def _parse_square(obj) -> tuple | None:
    """Parse a JSON object into a canonical square tuple, or None on error."""
    if not isinstance(obj, list) or len(obj) != 3:
        return None
    rows = []
    for row in obj:
        if not isinstance(row, list) or len(row) != 3:
            return None
        if not all(isinstance(v, int) for v in row):
            return None
        rows.append(tuple(row))
    return tuple(rows)


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    output_path = scratch_dir / OUTPUT_REL

    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    raw = output_path.read_text()
    if not raw.strip():
        return GradeResult(False, 0.0, "output artifact is empty")

    agent_squares: list[tuple] = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            return GradeResult(False, 0.0, f"line {lineno}: JSON parse error: {exc.msg}")
        sq = _parse_square(obj)
        if sq is None:
            return GradeResult(
                False, 0.0,
                f"line {lineno}: expected 3×3 integer matrix, got {obj!r}",
            )
        agent_squares.append(sq)

    # Check for duplicates
    seen: set[tuple] = set()
    duplicates: list[tuple] = []
    for sq in agent_squares:
        if sq in seen:
            duplicates.append(sq)
        seen.add(sq)
    if duplicates:
        return GradeResult(
            False, 0.0,
            f"{len(duplicates)} duplicate square(s) in output — remove duplicates",
        )

    reference = _all_latin_squares_3()
    agent_set = set(agent_squares)

    missing = reference - agent_set
    extra = agent_set - reference

    if missing or extra:
        parts = []
        if missing:
            parts.append(f"missing {len(missing)} square(s)")
        if extra:
            parts.append(f"{len(extra)} invalid/non-Latin square(s) in output")
        return GradeResult(
            False,
            round(len(agent_set & reference) / len(reference), 4),
            "; ".join(parts),
        )

    return GradeResult(True, 1.0, f"all {len(reference)} Latin squares enumerated correctly")
