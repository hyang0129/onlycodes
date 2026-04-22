"""Hidden grader for verification_heavy__expression_evaluator.

Correctness: evaluate(expr) matches expected value (numeric tolerance 1e-9),
or raises the expected exception type for error cases.
"""

from __future__ import annotations

import importlib.util
import math
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


_OK = object()

# (expr, expected) — expected is a float, or a type (subclass of Exception) the call must raise.
_TESTS: list[tuple[str, object]] = [
    ("1+2", 3.0),
    ("2+3*4", 14.0),
    ("(2+3)*4", 20.0),
    ("10-2-3", 5.0),
    ("10/2/5", 1.0),
    ("-5+3", -2.0),
    ("-(2+3)", -5.0),
    ("2*-3", -6.0),
    ("2 + 3 * 4", 14.0),
    ("  42 ", 42.0),
    ("3.14", 3.14),
    ("0.5 + 0.25", 0.75),
    ("((1+2)*(3+4))", 21.0),
    ("1 + 2 + 3 + 4 + 5", 15.0),
    ("100 / 4 * 2", 50.0),
    ("100 / (4 * 2)", 12.5),
    ("--5", 5.0),     # double unary minus
    ("-(-3)", 3.0),
    ("2*(3+4)-5", 9.0),
    ("0", 0.0),
    # error cases
    ("1/0", ZeroDivisionError),
    ("1 + ", ValueError),
    ("(1+2", ValueError),
    ("1+2)", ValueError),
    ("", ValueError),
]


def _close(got: float, want: float) -> bool:
    return math.isclose(got, want, rel_tol=1e-9, abs_tol=1e-9)


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

    if not hasattr(mod, "evaluate"):
        return GradeResult(False, 0.0, "solution.py does not define 'evaluate'")

    fn = mod.evaluate
    failures: list[str] = []
    for expr, expected in _TESTS:
        if isinstance(expected, type) and issubclass(expected, BaseException):
            try:
                got = fn(expr)
                failures.append(f"  evaluate({expr!r}): expected {expected.__name__}, got result {got!r}")
            except expected:
                pass
            except Exception as exc:
                failures.append(
                    f"  evaluate({expr!r}): expected {expected.__name__}, raised {type(exc).__name__}: {exc}"
                )
        else:
            try:
                got = fn(expr)
            except Exception as exc:
                failures.append(f"  evaluate({expr!r}): raised {type(exc).__name__}: {exc}")
                continue
            if not isinstance(got, (int, float)) or isinstance(got, bool):
                failures.append(f"  evaluate({expr!r}): expected float, got {type(got).__name__}")
            elif not _close(float(got), float(expected)):
                failures.append(f"  evaluate({expr!r}): expected {expected}, got {got}")

    n_pass = len(_TESTS) - len(failures)
    if failures:
        detail = f"{n_pass}/{len(_TESTS)} cases passed. Failures:\n" + "\n".join(failures)
        return GradeResult(False, round(n_pass / len(_TESTS), 4), detail)
    return GradeResult(True, 1.0, f"all {len(_TESTS)} cases passed")
