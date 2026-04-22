"""Hidden grader for verification_heavy__cron_next_fire.

Correctness: next_fire(expr, after) returns the exact expected datetime.
Tests cover common schedules, step values, restricted DOM+DOW OR semantics,
month/year rollovers, and leap-year handling.
"""

from __future__ import annotations

import importlib.util
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


OUTPUT_REL = "output/solution.py"


def _import_module(solution_path: Path):
    spec = importlib.util.spec_from_file_location("agent_solution", solution_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# (expr, after, expected)
_TESTS: list[tuple[str, datetime, datetime]] = [
    ("* * * * *",       datetime(2024, 1, 1, 12, 0),  datetime(2024, 1, 1, 12, 1)),
    ("0 * * * *",       datetime(2024, 1, 1, 12, 0),  datetime(2024, 1, 1, 13, 0)),
    ("0 0 * * *",       datetime(2024, 1, 1, 12, 0),  datetime(2024, 1, 2, 0, 0)),
    ("30 14 * * *",     datetime(2024, 1, 1, 12, 0),  datetime(2024, 1, 1, 14, 30)),
    ("30 14 * * *",     datetime(2024, 1, 1, 15, 0),  datetime(2024, 1, 2, 14, 30)),
    ("0 0 1 * *",       datetime(2024, 1, 1, 12, 0),  datetime(2024, 2, 1, 0, 0)),
    ("*/15 * * * *",    datetime(2024, 1, 1, 12, 0),  datetime(2024, 1, 1, 12, 15)),
    ("*/15 * * * *",    datetime(2024, 1, 1, 12, 14), datetime(2024, 1, 1, 12, 15)),
    ("0/20 * * * *",    datetime(2024, 1, 1, 12, 0),  datetime(2024, 1, 1, 12, 20)),
    ("0 9-17 * * 1-5",  datetime(2024, 1, 1, 12, 0),  datetime(2024, 1, 1, 13, 0)),  # Mon 13:00
    ("0 9-17 * * 1-5",  datetime(2024, 1, 5, 17, 0),  datetime(2024, 1, 8, 9, 0)),   # Fri->Mon
    ("0 0 29 2 *",      datetime(2023, 3, 1, 0, 0),   datetime(2024, 2, 29, 0, 0)),  # leap
    ("0 0 29 2 *",      datetime(2024, 3, 1, 0, 0),   datetime(2028, 2, 29, 0, 0)),  # next leap
    ("15,45 * * * *",   datetime(2024, 1, 1, 12, 20), datetime(2024, 1, 1, 12, 45)),
    ("15,45 * * * *",   datetime(2024, 1, 1, 12, 45), datetime(2024, 1, 1, 13, 15)),
    ("0 0 1 1 *",       datetime(2024, 6, 1, 0, 0),   datetime(2025, 1, 1, 0, 0)),
    ("0 0 * * 0",       datetime(2024, 1, 1, 0, 0),   datetime(2024, 1, 7, 0, 0)),   # Sunday
    ("0 0 15 * 1",      datetime(2024, 1, 1, 0, 0),   datetime(2024, 1, 8, 0, 0)),   # 15th OR Monday; Jan 8 2024 = Mon
    ("30 */6 * * *",    datetime(2024, 1, 1, 0, 0),   datetime(2024, 1, 1, 0, 30)),
    ("30 */6 * * *",    datetime(2024, 1, 1, 0, 30),  datetime(2024, 1, 1, 6, 30)),
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

    if not hasattr(mod, "next_fire"):
        return GradeResult(False, 0.0, "solution.py does not define 'next_fire'")

    fn = mod.next_fire
    failures: list[str] = []
    for expr, after, expected in _TESTS:
        try:
            got = fn(expr, after)
        except Exception as exc:
            failures.append(f"  next_fire({expr!r}, {after}): raised {type(exc).__name__}: {exc}")
            continue
        if not isinstance(got, datetime):
            failures.append(f"  next_fire({expr!r}, {after}): expected datetime, got {type(got).__name__}")
        elif got != expected:
            failures.append(f"  next_fire({expr!r}, {after}): expected {expected}, got {got}")

    n_pass = len(_TESTS) - len(failures)
    if failures:
        detail = f"{n_pass}/{len(_TESTS)} cases passed. Failures:\n" + "\n".join(failures)
        return GradeResult(False, round(n_pass / len(_TESTS), 4), detail)
    return GradeResult(True, 1.0, f"all {len(_TESTS)} cases passed")
