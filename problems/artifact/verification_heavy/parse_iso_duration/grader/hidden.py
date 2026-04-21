"""Hidden grader for verification_heavy__parse_iso_duration.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    The agent's output/solution.py must define ``parse_iso_duration(s) -> timedelta``
    that passes all 15 seeded property tests below. Each test failure is reported
    individually in ``detail``.

    The agent's module is imported in a subprocess to avoid polluting the harness.
    (The hidden grader subprocess is already isolated from the agent's environment —
    we import directly here since we're already in the grader subprocess.)

Determinism: all test inputs are fixed constants or seeded from instance_id.
"""

from __future__ import annotations

import importlib.util
import sys
import traceback
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


OUTPUT_REL = "output/solution.py"


def _import_module(solution_path: Path):
    """Import the agent's solution.py as a module."""
    spec = importlib.util.spec_from_file_location("agent_solution", solution_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _td(*, weeks=0, days=0, hours=0, minutes=0, seconds=0) -> timedelta:
    return timedelta(weeks=weeks, days=days, hours=hours, minutes=minutes, seconds=seconds)


# 15 fixed property tests — no randomness needed (determinism from fixed cases)
_TESTS: list[tuple[str, timedelta]] = [
    ("PT0S",               _td(seconds=0)),
    ("PT1S",               _td(seconds=1)),
    ("PT60S",              _td(seconds=60)),
    ("PT1M",               _td(minutes=1)),
    ("PT90M",              _td(minutes=90)),
    ("PT1H",               _td(hours=1)),
    ("PT1H30M",            _td(hours=1, minutes=30)),
    ("P1D",                _td(days=1)),
    ("P1W",                _td(weeks=1)),
    ("P7D",                _td(days=7)),
    ("P2DT6H",             _td(days=2, hours=6)),
    ("PT0.5S",             _td(seconds=0.5)),
    ("PT1.5H",             _td(hours=1.5)),
    ("P1W2DT3H4M5S",       _td(weeks=1, days=2, hours=3, minutes=4, seconds=5)),
    ("P3W5DT12H30M45S",    _td(weeks=3, days=5, hours=12, minutes=30, seconds=45)),
]


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    solution_path = scratch_dir / OUTPUT_REL

    if not solution_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced (output/solution.py missing)")

    try:
        mod = _import_module(solution_path)
    except Exception as exc:
        tb = traceback.format_exc()
        return GradeResult(False, 0.0, f"failed to import solution.py: {exc}\n{tb[:400]}")

    if not hasattr(mod, "parse_iso_duration"):
        return GradeResult(False, 0.0, "solution.py does not define 'parse_iso_duration'")

    fn = mod.parse_iso_duration

    failures: list[str] = []
    for iso_str, expected in _TESTS:
        try:
            result = fn(iso_str)
        except Exception as exc:
            failures.append(f"  {iso_str!r}: raised {type(exc).__name__}: {exc}")
            continue
        if not isinstance(result, timedelta):
            failures.append(
                f"  {iso_str!r}: expected timedelta, got {type(result).__name__}"
            )
        elif result != expected:
            failures.append(
                f"  {iso_str!r}: expected {expected!r}, got {result!r}"
            )

    n_pass = len(_TESTS) - len(failures)
    if failures:
        detail = f"{n_pass}/{len(_TESTS)} tests passed. Failures:\n" + "\n".join(failures)
        return GradeResult(False, round(n_pass / len(_TESTS), 4), detail)

    return GradeResult(True, 1.0, f"all {len(_TESTS)} property tests passed")
