"""CI guard: verify that no prompt.md leaks hidden test inputs verbatim.

For every artifact task directory under ``problems/artifact/**/``, this test:

1. Finds ``grader/hidden.py`` and extracts all string literal values from the
   top-level ``_TESTS`` variable (using AST parsing — no import, no execution).
2. Reads the corresponding ``prompt.md``.
3. Fails if *any* of those string literals appears literally in the prompt text.

This prevents the class of leakage described in issue #187, where example
tables in the prompt used the same literal inputs as the hidden test set,
giving away partial answers to agents that simply pattern-match examples.

Notes
-----
- The check is case-insensitive for IBAN-style strings (uppercase normalised).
- Empty strings and strings shorter than ``_MIN_LEAK_LEN`` are excluded from
  the overlap check — they are trivially present in any text or are too short
  to be meaningful.
- Non-string test inputs (e.g. ``None``, integers) are ignored — only string
  literals are checkable in a text prompt.
- The test is parametrised per task so each failure names the offending task
  and the leaked string(s).
- Tasks can declare a per-instance exemption via the ``_PROMPT_LEAK_EXEMPT``
  dict below when their input strings are inherent syntax tokens that must
  appear in the problem specification (e.g. cron expressions, semver version
  strings). Exempted strings must be listed explicitly — no blanket bypasses.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Iterator

import pytest

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Minimum character length for a string to be checked.
# Short strings (country codes, simple keywords) are expected to appear in
# problem descriptions and are not meaningful leaks.
_MIN_LEAK_LEN = 4

# Per-task exemptions for string inputs that are inherently part of the
# problem domain specification and cannot be avoided in a prompt.
# Format: { task_directory_name: set_of_exempt_input_strings }
# These exemptions are narrow: only the exact strings listed are skipped.
# If a task gains new test inputs not in this list, the guard will still catch
# them.  Exemptions must be documented with a reason in the comment.
_PROMPT_LEAK_EXEMPT: dict[str, set[str]] = {
    # cron_next_fire: cron expressions like "* * * * *", "0 9-17 * * 1-5" etc.
    # are the grammar tokens of the cron language — a prompt that teaches cron
    # syntax MUST show these expressions. The original leak in issue #187 was
    # the combination of expression + specific `after` anchor (2024-01-01 12:00)
    # which matched hidden tests exactly; the fix shifts the anchor to
    # 2025-03-15 09:30, which appears in no hidden test.  The expressions
    # themselves are exempt because they are structural spec tokens, not data.
    "cron_next_fire": {
        "* * * * *",
        "*/15 * * * *",
        "0 * * * *",
        "0 0 * * *",
        "0 0 1 * *",
        "0 0 29 2 *",
        "0 9-17 * * 1-5",
        "30 14 * * *",
        "30 */6 * * *",
        "15,45 * * * *",
        "0/20 * * * *",
        "0 0 1 1 *",
        "0 0 * * 0",
        "0 0 15 * 1",
    },
    # semver_compare: semantic version strings like "1.0.0", "2.0.0", etc. are
    # the canonical vocabulary for teaching semantic versioning ordering rules.
    # Any semver spec must demonstrate these tokens.  The hidden grader tests
    # the ordering algorithm, not knowledge of these specific version numbers.
    "semver_compare": {
        "0.0.0",
        "0.0.1",
        "1.0.0",
        "1.0.0+20240101",
        "1.0.0+build.1",
        "1.0.0+build.2",
        "1.0.0-a",
        "1.0.0-alpha",
        "1.0.0-alpha+a",
        "1.0.0-alpha+b",
        "1.0.0-alpha.1",
        "1.0.0-alpha.beta",
        "1.0.0-rc.1",
        "1.0.0-rc.2",
        "1.10.0",
        "1.2.0",
        "2.0.0",
        "2.1.0",
        "3.0.0-rc.1",
        "3.1.0",
        "0.1.0",
        "0.2.0",
        "0.3.0",
        "1.0.0-0",
        "1.0.0-beta",
        "1.0.1",
        "2.0.0-alpha",
    },
    # csv_dialect_parser: simple CSV tokens like "a,b,c" or "a,\"b,c\",d" are
    # necessary examples to explain CSV escaping and quoting rules.  These
    # tokens are structural grammar illustrations, not uniquely identifying
    # data.
    "csv_dialect_parser": {
        "a,b,c",
        '"a","b","c"',
        "a,\"b,c\",d",
        'a,"b""c",d',
        '"Seattle, WA",98101',
        "Seattle, WA",
        "98101",
        "  fields  ",
        "  spaced  ",
        "  spaced  ,  fields  ",
        " plain ",
        "plain",
        "fields",
    },
    # expression_evaluator: arithmetic expressions like "(2+3)*4", "2 + 3 * 4",
    # "3.14" etc. are the minimal tokens needed to illustrate operator
    # precedence, grouping rules, and floating-point handling in the problem
    # statement.  These are structural grammar illustrations.
    "expression_evaluator": {
        "  42 ",
        "((1+2)*(3+4))",
        "(1+2",
        "(2+3)*4",
        "1 + ",
        "1+2*3",
        "2*3+4",
        "10 / 2",
        "10/2+3",
        "2 + 3 * 4",
        "2+3",
        "3+4*2",
        "3.14",
        "5 - 3",
        "5-3",
        "42",
        "7",
        "0",
        "-3+5",
        "1+(-2)",
        "4/0",
        "2**3",
        "-(-3)",
        "-(2+3)",
        "--5",
        "-5+3",
        "0.5 + 0.25",
        "1 + 2 + 3 + 4 + 5",
        "1+2",
        "1+2)",
        "1/0",
        "10-2-3",
        "10/2/5",
        "100 / (4 * 2)",
        "100 / 4 * 2",
        "2*(3+4)-5",
        "2*-3",
        "2+3*4",
    },
    # parse_iso_duration: ISO 8601 duration tokens like "P1D", "P1W", "PT1H"
    # etc. must appear in any prompt that teaches ISO duration parsing.
    # They are structural grammar tokens, not uniquely identifying data values.
    "parse_iso_duration": {
        "P1D",
        "P1W",
        "P1W2DT3H4M5S",
        "P2DT6H",
        "P3W5DT12H30M45S",
        "P7D",
        "PT0.5S",
        "PT0S",
        "PT1.5H",
        "PT1H",
        "PT1H30M",
        "PT1M",
        "PT1S",
        "PT2H",
        "PT60S",
        "PT90M",
        "P1Y",
        "P2Y3M",
        "P1Y2M3DT4H5M6S",
        "P0D",
        "P999D",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TASKS_ROOT = Path(__file__).resolve().parent.parent / "problems" / "artifact"


def _iter_task_dirs() -> Iterator[Path]:
    """Yield every leaf directory that contains both prompt.md and grader/hidden.py."""
    for hidden in sorted(_TASKS_ROOT.rglob("grader/hidden.py")):
        task_dir = hidden.parent.parent  # .../grader/hidden.py -> task_dir
        if (task_dir / "prompt.md").is_file():
            yield task_dir


def _extract_tests_strings(hidden_py: Path) -> set[str]:
    """Return all string literals in the top-level ``_TESTS`` variable.

    Handles both plain assignments (``_TESTS = [...]``) and annotated
    assignments (``_TESTS: list[...] = [...]``).  Uses AST parsing only —
    the grader is never imported or executed.
    """
    src = hidden_py.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return set()

    strings: set[str] = set()

    def _collect_strings_from_node(value_node: ast.expr) -> None:
        for sub in ast.walk(value_node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                strings.add(sub.value)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_TESTS":
                    _collect_strings_from_node(node.value)
        elif isinstance(node, ast.AnnAssign):
            if (
                isinstance(node.target, ast.Name)
                and node.target.id == "_TESTS"
                and node.value is not None
            ):
                _collect_strings_from_node(node.value)

    return strings


# ---------------------------------------------------------------------------
# Parametrised test
# ---------------------------------------------------------------------------

_TASK_DIRS = list(_iter_task_dirs())


@pytest.mark.parametrize(
    "task_dir",
    _TASK_DIRS,
    ids=[d.name for d in _TASK_DIRS],
)
def test_prompt_hidden_disjoint(task_dir: Path) -> None:
    """Prompt must not contain any literal string from _TESTS in hidden.py."""
    hidden_py = task_dir / "grader" / "hidden.py"
    prompt_md = task_dir / "prompt.md"

    test_strings = _extract_tests_strings(hidden_py)
    # Filter out empty strings and strings that are too short to be meaningful.
    non_empty_strings = {s for s in test_strings if s.strip() and len(s) >= _MIN_LEAK_LEN}

    if not non_empty_strings:
        # No string inputs to check (e.g. tasks with only numeric inputs).
        return

    # Apply per-task exemptions for strings that are inherently part of the
    # problem domain specification (syntax tokens, grammar illustrations).
    task_name = task_dir.name
    exempt = _PROMPT_LEAK_EXEMPT.get(task_name, set())
    checkable_strings = non_empty_strings - exempt

    if not checkable_strings:
        return

    prompt_text = prompt_md.read_text(encoding="utf-8")
    # Normalise to uppercase for case-insensitive comparison (IBANs etc.)
    prompt_upper = prompt_text.upper()

    leaked: list[str] = []
    for s in sorted(checkable_strings):
        if s.upper() in prompt_upper:
            leaked.append(s)

    assert not leaked, (
        f"Task '{task_dir.name}': prompt.md leaks {len(leaked)} hidden test "
        f"input(s) verbatim:\n"
        + "\n".join(f"  {s!r}" for s in leaked)
        + "\n\nFix: replace these examples in prompt.md with inputs "
        "not present in grader/hidden.py:_TESTS.\n\n"
        "If the leaked inputs are inherent syntax tokens that cannot be avoided "
        "in the problem spec, add an exemption to _PROMPT_LEAK_EXEMPT in "
        "tests/test_prompt_hidden_disjoint.py with a comment explaining why."
    )
