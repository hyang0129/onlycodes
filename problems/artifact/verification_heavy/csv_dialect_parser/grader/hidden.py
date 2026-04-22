"""Hidden grader for verification_heavy__csv_dialect_parser.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    The agent's output/solution.py must define ``parse_csv_line(line) -> list[str]``
    that passes all 20 seeded fixed cases below. Each failure is reported
    individually in ``detail``.

Determinism: all test inputs are fixed constants.
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


_TESTS: list[tuple[str, list[str]]] = [
    ("a,b,c", ["a", "b", "c"]),
    ("", [""]),
    (",", ["", ""]),
    (",,", ["", "", ""]),
    ("a", ["a"]),
    ("a,", ["a", ""]),
    (",a", ["", "a"]),
    ('"a","b","c"', ["a", "b", "c"]),
    ('a,"b,c",d', ["a", "b,c", "d"]),
    ('a,"b""c",d', ["a", 'b"c', "d"]),
    ('"Seattle, WA",98101', ["Seattle, WA", "98101"]),
    ('"",""', ["", ""]),
    ('"he said ""hi""",ok', ['he said "hi"', "ok"]),
    ("1,2,3,4,5", ["1", "2", "3", "4", "5"]),
    ("name,age,city", ["name", "age", "city"]),
    ('"a,b,c"', ["a,b,c"]),
    ('"a","b,c,d","e"', ["a", "b,c,d", "e"]),
    ("  spaced  ,  fields  ", ["  spaced  ", "  fields  "]),
    ('"with space", plain ,"more"', ["with space", " plain ", "more"]),
    ('x,"",y', ["x", "", "y"]),
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

    if not hasattr(mod, "parse_csv_line"):
        return GradeResult(False, 0.0, "solution.py does not define 'parse_csv_line'")

    fn = mod.parse_csv_line
    failures: list[str] = []
    for line, expected in _TESTS:
        try:
            got = fn(line)
        except Exception as exc:
            failures.append(f"  {line!r}: raised {type(exc).__name__}: {exc}")
            continue
        if not isinstance(got, list):
            failures.append(f"  {line!r}: expected list, got {type(got).__name__}")
        elif got != expected:
            failures.append(f"  {line!r}: expected {expected!r}, got {got!r}")

    n_pass = len(_TESTS) - len(failures)
    if failures:
        detail = f"{n_pass}/{len(_TESTS)} tests passed. Failures:\n" + "\n".join(failures)
        return GradeResult(False, round(n_pass / len(_TESTS), 4), detail)

    return GradeResult(True, 1.0, f"all {len(_TESTS)} cases passed")
