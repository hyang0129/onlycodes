#!/usr/bin/env python3
"""Lint that flags answer leaks in artifact-graded grader detail strings.

SCHEMA_ARTIFACT.md §3.3 forbids embedding the reference value in the
``detail`` field of a ``GradeResult``:

    Not acceptable: ``expected 42, got 41`` if the reference value is itself
    the answer.

This lint walks ``problems/artifact/*/grader/hidden.py`` and uses Python's
``ast`` module to inspect every string passed to a ``GradeResult`` constructor
(positionally or as the ``detail=`` keyword). For each f-string, it inspects
the literal-text segments only — not the interpolated values — and flags any
literal text that contains a "leak token" immediately followed (within 4
characters) by a curly brace.

The leak tokens are: ``expected``, ``optimal``, ``truth``, ``reference``,
``want``, and ``ref``. The match is case-insensitive.

Allowed exceptions:
- Type complaints: ``expected int, got list``, ``want list, got str``. The
  rule does NOT trigger when the next interpolated value resolves to a
  ``type(...).__name__`` expression OR the literal text after the brace is
  ``.__name__`` / ``).__name__``.
- Bare type-name interpolations like ``f"{type(x).__name__}"`` in failure
  messages are allowed.

Exit code:
    0  — no violations
    1  — at least one violation (also printed to stderr)

Usage:
    python tools/check_grader_leaks.py [--root path/to/onlycodes]
    python tools/check_grader_leaks.py --self-test    # run unit tests
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path
from typing import Iterable, Iterator, NamedTuple


LEAK_TOKENS = ("expected", "optimal", "truth", "reference", "want", "ref")

# Match a leak token anywhere in the literal segment that immediately
# precedes an interpolation. We do NOT require a brace adjacency in the
# regex; instead the AST scan only considers segments that are followed
# by a FormattedValue, and only the last 30 chars of those segments.
_LEAK_TOKEN_RE = re.compile(
    r"\b(?P<token>" + "|".join(LEAK_TOKENS) + r")\b",
    re.IGNORECASE,
)


class Violation(NamedTuple):
    file: Path
    line: int
    col: int
    snippet: str
    reason: str


def _is_grade_result_call(call: ast.Call) -> bool:
    """Return True if `call` is a ``GradeResult(...)`` constructor."""
    f = call.func
    if isinstance(f, ast.Name) and f.id == "GradeResult":
        return True
    if isinstance(f, ast.Attribute) and f.attr == "GradeResult":
        return True
    return False


def _detail_args(call: ast.Call) -> Iterator[ast.expr]:
    """Yield the AST node(s) corresponding to the ``detail`` argument.

    GradeResult has signature ``(passed, score, detail)``; detail is positional
    arg index 2 OR keyword arg ``detail=...``.
    """
    if len(call.args) >= 3:
        yield call.args[2]
    for kw in call.keywords:
        if kw.arg == "detail":
            yield kw.value


def _next_typed_segment(parts: list[ast.expr], idx: int) -> bool:
    """Return True if the FormattedValue at index ``idx`` is a type-name expr.

    Examples: ``type(x).__name__``, ``type(x).__qualname__``, ``x.__class__.__name__``.
    """
    if idx >= len(parts):
        return False
    node = parts[idx]
    if not isinstance(node, ast.FormattedValue):
        return False
    val = node.value
    # Walk the expression and look for `__name__` or `__qualname__` attribute.
    for sub in ast.walk(val):
        if isinstance(sub, ast.Attribute) and sub.attr in (
            "__name__",
            "__qualname__",
        ):
            return True
    return False


def _scan_joined_str(
    node: ast.JoinedStr,
    file: Path,
) -> Iterator[Violation]:
    """Walk an f-string and flag literal segments that introduce a non-typed
    interpolation with a leak token nearby.

    Rule: for each FormattedValue at index i (i >= 1), look at the preceding
    Constant string segment. If that segment contains a leak token within the
    last 30 characters AND the FormattedValue is NOT a type-name expression,
    flag it.
    """
    parts = list(node.values)
    for i, part in enumerate(parts):
        if not isinstance(part, ast.FormattedValue):
            continue
        # Type-name interpolations are an allowed exception.
        if _next_typed_segment(parts, i):
            continue
        if i == 0:
            continue
        prev = parts[i - 1]
        if not isinstance(prev, ast.Constant) or not isinstance(prev.value, str):
            continue
        # Only the last 30 characters of the preceding literal matter — far-away
        # tokens are typically descriptive, not adjacent to the value.
        suffix = prev.value[-30:]
        m = _LEAK_TOKEN_RE.search(suffix)
        if not m:
            continue
        yield Violation(
            file=file,
            line=node.lineno,
            col=node.col_offset,
            snippet=prev.value.strip()[-60:],
            reason=(
                f"detail contains '{m.group('token')}' adjacent to an "
                f"interpolated value (SCHEMA §3.3)"
            ),
        )


def _scan_constant(node: ast.Constant, file: Path) -> Iterator[Violation]:
    """Walk a plain str constant. A pure literal can't interpolate but it can
    leak via .format() / %s — flag patterns where a leak token sits next to a
    formatting placeholder."""
    if not isinstance(node.value, str):
        return
    text = node.value
    # Look for leak token followed within 4 chars by `{`, `%s`, `%d`, etc.
    pattern = re.compile(
        r"\b(" + "|".join(LEAK_TOKENS) + r")\b[^a-zA-Z]{0,4}"
        r"(\{|%[sdrf]|\{[^}]*\})",
        re.IGNORECASE,
    )
    if pattern.search(text):
        yield Violation(
            file=file,
            line=node.lineno,
            col=node.col_offset,
            snippet=text.strip()[:80],
            reason="detail string contains leak token adjacent to a placeholder",
        )


def scan_file(path: Path) -> list[Violation]:
    """Return all violations in a single grader file."""
    src = path.read_text()
    tree = ast.parse(src)
    out: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_grade_result_call(node):
            continue
        for detail in _detail_args(node):
            if isinstance(detail, ast.JoinedStr):
                out.extend(_scan_joined_str(detail, path))
            elif isinstance(detail, ast.Constant):
                out.extend(_scan_constant(detail, path))
            # Other forms (variable, function call) — we can't statically
            # check them. Authors should use literal/f-string detail.
    return out


def find_graders(root: Path) -> list[Path]:
    return sorted(root.glob("problems/artifact/*/*/grader/hidden.py"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="repo root (default: parent of tools/)",
    )
    p.add_argument(
        "--self-test",
        action="store_true",
        help="run unit tests against handcrafted leaky / clean snippets",
    )
    args = p.parse_args(argv)

    if args.self_test:
        return _self_test()

    files = find_graders(args.root)
    if not files:
        print(f"no grader files found under {args.root}", file=sys.stderr)
        return 2

    violations: list[Violation] = []
    for f in files:
        violations.extend(scan_file(f))

    if violations:
        print(f"FAIL: {len(violations)} answer-leak violation(s) in "
              f"{len({v.file for v in violations})} grader file(s):",
              file=sys.stderr)
        for v in violations:
            rel = v.file.relative_to(args.root)
            print(f"  {rel}:{v.line}: {v.reason}", file=sys.stderr)
            print(f"      snippet: {v.snippet!r}", file=sys.stderr)
        return 1

    print(f"OK: scanned {len(files)} grader file(s); no leaks found")
    return 0


# ────────────────────────────── self-test ─────────────────────────────────

_LEAKY_SAMPLES = [
    # Failure-path leaks
    'GradeResult(False, 0.0, f"min_coins {x} is not optimal (optimal={opt})")',
    'GradeResult(False, 0.0, f"endpoint {ep}: count {c}, want {true_count}")',
    'GradeResult(False, 0.0, f"value {v} != expected {wanted}")',
    'GradeResult(False, 0.0, f"got {x}, vs ref {ref_x}")',
    'GradeResult(False, 0.0, f"truth was {truth_v}, got {got}")',
    # Success-path leak
    'GradeResult(True, 1.0, f"optimal num_bins={optimal}")',
    # Keyword argument
    'GradeResult(passed=False, score=0.0, detail=f"size {s} != expected {wanted}")',
]

_CLEAN_SAMPLES = [
    # Type complaints (allowed)
    'GradeResult(False, 0.0, f"min_coins must be int, got {type(x).__name__}")',
    'GradeResult(False, 0.0, f"value must be a number, got {type(v).__name__}")',
    'GradeResult(False, 0.0, f"expected int, got {type(got).__name__} {got!r}")',
    # Generic mismatch messages (allowed)
    'GradeResult(False, 0.0, f"min_coins {x} is not optimal")',
    'GradeResult(False, 0.0, "endpoint mismatch")',
    'GradeResult(False, 0.0, f"row {i}: count {c} mismatch")',
    # Plain success
    'GradeResult(True, 1.0, "all balances correct")',
    # Detail with key/index in message (no leak token before brace)
    'GradeResult(False, 0.0, f"row {i}: bad shape")',
]


def _scan_str_module(src: str) -> list[Violation]:
    tree = ast.parse(src)
    out: list[Violation] = []
    fake_path = Path("<test>")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_grade_result_call(node):
            continue
        for detail in _detail_args(node):
            if isinstance(detail, ast.JoinedStr):
                out.extend(_scan_joined_str(detail, fake_path))
            elif isinstance(detail, ast.Constant):
                out.extend(_scan_constant(detail, fake_path))
    return out


def _self_test() -> int:
    failed = 0
    for src in _LEAKY_SAMPLES:
        v = _scan_str_module(src)
        if not v:
            print(f"FAIL: leaky sample not flagged: {src}", file=sys.stderr)
            failed += 1
    for src in _CLEAN_SAMPLES:
        v = _scan_str_module(src)
        if v:
            print(f"FAIL: clean sample falsely flagged: {src}\n  -> {v}", file=sys.stderr)
            failed += 1
    if failed:
        print(f"\n{failed} self-test failure(s)", file=sys.stderr)
        return 1
    print(f"OK: self-test passed ({len(_LEAKY_SAMPLES)} leaky + "
          f"{len(_CLEAN_SAMPLES)} clean samples)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
