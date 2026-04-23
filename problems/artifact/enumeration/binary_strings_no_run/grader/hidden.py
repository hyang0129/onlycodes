"""Hidden grader for enumeration__binary_strings_no_run.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    Every length-10 binary string with no run of '1's longer than 2 must appear
    exactly once in output/strings.jsonl. There are 504 such strings (tribonacci-
    related count).

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


OUTPUT_REL = "output/strings.jsonl"
LENGTH = 10
MAX_RUN = 2


def _ground_truth() -> set[str]:
    forbidden = "1" * (MAX_RUN + 1)  # "111"
    result: set[str] = set()
    for bits in itertools.product("01", repeat=LENGTH):
        s = "".join(bits)
        if forbidden in s:
            continue
        result.add(s)
    return result


def _valid(s: str) -> bool:
    if not isinstance(s, str) or len(s) != LENGTH:
        return False
    if any(ch not in "01" for ch in s):
        return False
    return ("1" * (MAX_RUN + 1)) not in s


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    output_path = scratch_dir / OUTPUT_REL

    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    raw = output_path.read_text()
    if not raw.strip():
        return GradeResult(False, 0.0, "output artifact is empty")

    agent_strs: list[str] = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            return GradeResult(False, 0.0, f"line {lineno}: JSON parse error: {exc.msg}")
        if not isinstance(obj, str):
            return GradeResult(False, 0.0, f"line {lineno}: expected JSON string, got {type(obj).__name__}")
        if not _valid(obj):
            return GradeResult(
                False, 0.0,
                f"line {lineno}: invalid string {obj!r} (length != {LENGTH}, non-binary chars, or contains run of > {MAX_RUN} '1's)",
            )
        agent_strs.append(obj)

    seen: set[str] = set()
    dupes: list[str] = []
    for s in agent_strs:
        if s in seen:
            dupes.append(s)
        seen.add(s)
    if dupes:
        return GradeResult(False, 0.0, f"{len(dupes)} duplicate string(s)")

    reference = _ground_truth()
    agent_set = set(agent_strs)
    missing = reference - agent_set
    extra = agent_set - reference  # shouldn't occur

    if missing or extra:
        parts = []
        if missing:
            parts.append(f"missing {len(missing)} string(s)")
        if extra:
            parts.append(f"{len(extra)} unexpected string(s)")
        return GradeResult(
            False,
            round(len(agent_set & reference) / len(reference), 4),
            "; ".join(parts),
        )

    return GradeResult(True, 1.0, f"all {len(reference)} qualifying strings enumerated")
