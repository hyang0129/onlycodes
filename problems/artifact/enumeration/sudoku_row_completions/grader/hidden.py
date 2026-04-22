"""Hidden grader for enumeration__sudoku_row_completions.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    Enumerate every length-9 permutation of {1..9} that respects both
    fixed[] (pinned values) and forbidden[] (forbidden-value lists) from
    workspace/row.json. Compare to agent output as a set.

Determinism: pure enumeration.
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


OUTPUT_REL = "output/completions.jsonl"
INPUT_REL = "row.json"


def _ground_truth(fixed: list, forbidden: list[list[int]]) -> set[tuple]:
    # Determine remaining values to place at unfixed positions.
    digits = set(range(1, 10))
    placed = {v for v in fixed if v is not None}
    remaining = sorted(digits - placed)
    free_positions = [i for i, v in enumerate(fixed) if v is None]

    # Pre-build forbidden as sets
    forb_sets = [set(f) for f in forbidden]

    result: set[tuple] = set()
    for perm in itertools.permutations(remaining):
        row = list(fixed)
        ok = True
        for pos, val in zip(free_positions, perm):
            if val in forb_sets[pos]:
                ok = False
                break
            row[pos] = val
        if not ok:
            continue
        # Also check fixed cells don't accidentally violate forbidden (shouldn't happen,
        # but be defensive).
        for i, v in enumerate(row):
            if v in forb_sets[i]:
                ok = False
                break
        if ok:
            result.add(tuple(row))
    return result


def _parse_row(obj) -> tuple | None:
    if not isinstance(obj, list) or len(obj) != 9:
        return None
    if not all(isinstance(v, int) for v in obj):
        return None
    if sorted(obj) != list(range(1, 10)):
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
        fixed = data["fixed"]
        forbidden = data["forbidden"]
        if not isinstance(fixed, list) or len(fixed) != 9:
            raise ValueError("fixed must be length-9 list")
        if not isinstance(forbidden, list) or len(forbidden) != 9:
            raise ValueError("forbidden must be length-9 list")
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        return GradeResult(False, 0.0, f"malformed workspace input: {exc}")

    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    raw = output_path.read_text()
    if not raw.strip():
        return GradeResult(False, 0.0, "output artifact is empty")

    agent_rows: list[tuple] = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            return GradeResult(False, 0.0, f"line {lineno}: JSON parse error: {exc.msg}")
        row = _parse_row(obj)
        if row is None:
            return GradeResult(
                False, 0.0,
                f"line {lineno}: expected length-9 permutation of 1..9, got {obj!r}",
            )
        # Check fixed positions
        for i, v in enumerate(fixed):
            if v is not None and row[i] != v:
                return GradeResult(
                    False, 0.0,
                    f"line {lineno}: position {i} must be {v} (fixed) but got {row[i]}",
                )
        # Check forbidden positions
        for i, bad_list in enumerate(forbidden):
            if row[i] in set(bad_list):
                return GradeResult(
                    False, 0.0,
                    f"line {lineno}: position {i} has forbidden value {row[i]}",
                )
        agent_rows.append(row)

    seen: set[tuple] = set()
    dupes: list[tuple] = []
    for r in agent_rows:
        if r in seen:
            dupes.append(r)
        seen.add(r)
    if dupes:
        return GradeResult(False, 0.0, f"{len(dupes)} duplicate row(s) in output")

    reference = _ground_truth(fixed, forbidden)
    agent_set = set(agent_rows)
    missing = reference - agent_set
    extra = agent_set - reference  # would only be non-empty if somehow passed all per-line checks but not in reference (shouldn't occur)

    if missing or extra:
        parts = []
        if missing:
            parts.append(f"missing {len(missing)} valid completion(s)")
        if extra:
            parts.append(f"{len(extra)} unexpected row(s)")
        return GradeResult(
            False,
            round(len(agent_set & reference) / max(len(reference), 1), 4),
            "; ".join(parts),
        )

    return GradeResult(
        True, 1.0,
        f"all {len(reference)} valid row completions enumerated",
    )
