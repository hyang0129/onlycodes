"""Hidden grader for verification_heavy__json_pointer_rfc6901.

Tests resolve() and set_at() against a curated RFC 6901 fixture. Each test
case is independent (the grader deep-copies the base doc before each case).
"""

from __future__ import annotations

import copy
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


def _base_doc() -> dict:
    return {
        "": "empty-key",
        "a/b": "slash-in-key",
        "m~n": "tilde-in-key",
        "foo": ["bar", "baz"],
        "": "empty-key",  # duplicate intentional — last wins
        "nested": {
            "x": 1,
            "y": {"z": [10, 20, 30]},
        },
        "arr": [{"k": "v"}, [1, 2, 3], None],
        "primitives": 42,
    }


# Resolve tests: (pointer, expected) where expected is a value, or a type to assert raised.
_RESOLVE_TESTS: list[tuple[str, object]] = [
    ("", "__DOC__"),  # special sentinel: compare to full doc
    ("/a~1b", "slash-in-key"),
    ("/m~0n", "tilde-in-key"),
    ("/foo/0", "bar"),
    ("/foo/1", "baz"),
    ("/nested/x", 1),
    ("/nested/y/z/2", 30),
    ("/arr/0/k", "v"),
    ("/arr/1/1", 2),
    ("/primitives", 42),
    ("/", "empty-key"),  # key = ""
    # Error cases
    ("/missing", KeyError),
    ("/foo/9", KeyError),
    ("/foo/-", KeyError),  # '-' on array not allowed in resolve
    ("/primitives/x", KeyError),  # traverse into int
    ("abc", ValueError),  # invalid pointer
    ("/foo/01", KeyError),  # leading zero
    ("/foo/-1", KeyError),  # negative
]


# Set tests: (pointer, value, check_fn) where check_fn(doc) -> bool.
# Expected-exception form: (pointer, value, <exception type>)
_SET_TESTS: list[tuple[str, object, object]] = [
    ("/nested/x", 99,
        lambda d: d["nested"]["x"] == 99),
    ("/foo/0", "BAR",
        lambda d: d["foo"][0] == "BAR"),
    ("/foo/-", "qux",
        lambda d: d["foo"] == ["bar", "baz", "qux"]),
    ("/foo/2", "added",
        lambda d: d["foo"] == ["bar", "baz", "added"]),  # idx == len → append
    ("/nested/y/z/0", 1000,
        lambda d: d["nested"]["y"]["z"][0] == 1000),
    ("/nested/new_key", {"k": "v"},
        lambda d: d["nested"]["new_key"] == {"k": "v"}),
    ("/a~1b", "updated",
        lambda d: d["a/b"] == "updated"),
    ("/arr/2", "replaced",
        lambda d: d["arr"][2] == "replaced"),
    ("/nested/y/z/-", 40,
        lambda d: d["nested"]["y"]["z"] == [10, 20, 30, 40]),
    # Error cases
    ("", 1, ValueError),
    ("/foo/9", "x", KeyError),      # index beyond len
    ("/missing/inner", 1, KeyError),  # parent missing (no auto-create)
    ("abc", 1, ValueError),          # invalid pointer syntax
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

    if not hasattr(mod, "resolve") or not hasattr(mod, "set_at"):
        return GradeResult(False, 0.0, "solution.py missing 'resolve' or 'set_at'")

    resolve = mod.resolve
    set_at = mod.set_at

    failures: list[str] = []

    for ptr, expected in _RESOLVE_TESTS:
        doc = _base_doc()
        if isinstance(expected, type) and issubclass(expected, BaseException):
            try:
                got = resolve(doc, ptr)
                failures.append(f"  resolve({ptr!r}): expected {expected.__name__}, got {got!r}")
            except expected:
                pass
            except Exception as exc:
                failures.append(
                    f"  resolve({ptr!r}): expected {expected.__name__}, raised {type(exc).__name__}: {exc}"
                )
        else:
            try:
                got = resolve(doc, ptr)
            except Exception as exc:
                failures.append(f"  resolve({ptr!r}): raised {type(exc).__name__}: {exc}")
                continue
            want = doc if expected == "__DOC__" else expected
            if got != want:
                failures.append(f"  resolve({ptr!r}): expected {want!r}, got {got!r}")

    for ptr, value, check in _SET_TESTS:
        doc = _base_doc()
        if isinstance(check, type) and issubclass(check, BaseException):
            try:
                set_at(doc, ptr, value)
                failures.append(f"  set_at({ptr!r}, {value!r}): expected {check.__name__}, no exception")
            except check:
                pass
            except Exception as exc:
                failures.append(
                    f"  set_at({ptr!r}, {value!r}): expected {check.__name__}, raised {type(exc).__name__}: {exc}"
                )
        else:
            snapshot = copy.deepcopy(doc)
            try:
                set_at(doc, ptr, value)
            except Exception as exc:
                failures.append(f"  set_at({ptr!r}, {value!r}): raised {type(exc).__name__}: {exc}")
                continue
            try:
                ok = bool(check(doc))
            except Exception as exc:
                failures.append(f"  set_at({ptr!r}, {value!r}): check raised {type(exc).__name__}: {exc}")
                continue
            if not ok:
                failures.append(
                    f"  set_at({ptr!r}, {value!r}): postcondition false (doc before={snapshot!r}, after={doc!r})"
                )

    total = len(_RESOLVE_TESTS) + len(_SET_TESTS)
    n_pass = total - len(failures)
    if failures:
        detail = f"{n_pass}/{total} cases passed. Failures:\n" + "\n".join(failures[:15])
        if len(failures) > 15:
            detail += f"\n  ... ({len(failures) - 15} more)"
        return GradeResult(False, round(n_pass / total, 4), detail)
    return GradeResult(True, 1.0, f"all {total} cases passed")
