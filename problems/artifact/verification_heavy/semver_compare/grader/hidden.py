"""Hidden grader for verification_heavy__semver_compare.

Contract: ``grade(scratch_dir: Path) -> GradeResult``.

Correctness: compare_semver(a, b) must return -1/0/+1 per SemVer v2.0.0
precedence across 25 fixed cases.
"""

from __future__ import annotations

import importlib.util
import traceback
from dataclasses import dataclass
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


# (a, b, expected)
_TESTS: list[tuple[str, str, int]] = [
    ("1.0.0", "1.0.0", 0),
    ("1.0.0", "2.0.0", -1),
    ("2.0.0", "1.0.0", 1),
    ("1.0.0", "1.1.0", -1),
    ("1.2.0", "1.10.0", -1),
    ("1.10.0", "1.2.0", 1),
    ("1.0.1", "1.0.10", -1),
    ("0.0.0", "0.0.1", -1),
    ("1.0.0-alpha", "1.0.0", -1),
    ("1.0.0", "1.0.0-alpha", 1),
    ("1.0.0-alpha", "1.0.0-alpha.1", -1),
    ("1.0.0-alpha.1", "1.0.0-alpha.beta", -1),
    ("1.0.0-alpha.beta", "1.0.0-beta", -1),
    ("1.0.0-beta", "1.0.0-beta.2", -1),
    ("1.0.0-beta.2", "1.0.0-beta.11", -1),
    ("1.0.0-beta.11", "1.0.0-rc.1", -1),
    ("1.0.0-rc.1", "1.0.0", -1),
    ("1.0.0-rc.1", "1.0.0-rc.2", -1),
    ("1.0.0-alpha", "1.0.0-alpha", 0),
    ("1.0.0+build.1", "1.0.0+build.2", 0),
    ("1.0.0+20240101", "1.0.0", 0),
    ("1.0.0-alpha+a", "1.0.0-alpha+b", 0),
    ("2.0.0-rc.1", "2.0.0-rc.1", 0),
    ("1.2.3-4", "1.2.3-5", -1),
    ("1.0.0-1", "1.0.0-a", -1),
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

    if not hasattr(mod, "compare_semver"):
        return GradeResult(False, 0.0, "solution.py does not define 'compare_semver'")

    fn = mod.compare_semver
    failures: list[str] = []
    for a, b, expected in _TESTS:
        try:
            got = fn(a, b)
        except Exception as exc:
            failures.append(f"  compare_semver({a!r},{b!r}): raised {type(exc).__name__}: {exc}")
            continue
        # Normalise to -1/0/+1 to accept any signed int convention.
        if got is True or got is False or not isinstance(got, int):
            failures.append(f"  compare_semver({a!r},{b!r}): expected int, got {type(got).__name__} {got!r}")
            continue
        norm = -1 if got < 0 else (1 if got > 0 else 0)
        if norm != expected:
            failures.append(f"  compare_semver({a!r},{b!r}): expected {expected}, got {got}")

    n_pass = len(_TESTS) - len(failures)
    if failures:
        detail = f"{n_pass}/{len(_TESTS)} cases passed. Failures:\n" + "\n".join(failures)
        return GradeResult(False, round(n_pass / len(_TESTS), 4), detail)
    return GradeResult(True, 1.0, f"all {len(_TESTS)} cases passed")
