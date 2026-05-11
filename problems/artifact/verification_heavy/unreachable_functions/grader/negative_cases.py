"""Per-task negative cases for ``verification_heavy__unreachable_functions``.

The prompt requires every output line to carry **both** ``function`` AND
``module`` keys. Originally the grader only validated ``function`` — the
``module`` field was read from the reference but never checked against
the agent's output, so a JSONL with a bogus or missing module slipped
through; that was issue #171's ``unreachable_functions module`` bug.

Issue #166 tightened the grader to (a) require a ``module`` key and (b)
validate it against the file each function was defined in (computed by
the same AST walk that drives reachability). The ``drop_module_field``
and ``wrong_module_value`` cases below now lock that behaviour in
(``currently_caught=True``).

Issue #185 fixed an empty-output false-negative: the grader now computes the
reference *before* the empty check, so an empty output against a non-empty
reference produces "output artifact is empty but N unreachable function(s) were
expected" (not the old bare "output artifact is empty").
"""

from __future__ import annotations

import json

from swebench.artifact_negative import (
    NegativeCase,
    _mutate_empty,
    _mutate_truncate_half,
    _mutate_wrap_in_list,
)


def _mutate_drop_module(text: str) -> str:
    """Remove the ``module`` key from every line.

    The prompt requires both keys. The current grader only validates
    ``function``, so this passes today.
    """
    out_lines: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        obj.pop("module", None)
        out_lines.append(json.dumps(obj))
    return "\n".join(out_lines) + "\n"


def _mutate_wrong_module(text: str) -> str:
    """Replace every ``module`` value with a known-wrong placeholder."""
    out_lines: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if "module" in obj:
            obj["module"] = "WRONG_MODULE"
        out_lines.append(json.dumps(obj))
    return "\n".join(out_lines) + "\n"


def _mutate_rename_function_key(text: str) -> str:
    """Rename ``function`` to ``func`` — caught by the existing key check."""
    return text.replace('"function":', '"func":')


def _mutate_rename_one_function(text: str) -> str:
    """Rename one function value to a guaranteed-wrong name."""
    out_lines: list[str] = []
    first = True
    for line in text.splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if first and "function" in obj:
            obj["function"] = obj["function"] + "_RENAMED"
            first = False
        out_lines.append(json.dumps(obj))
    return "\n".join(out_lines) + "\n"


def _mutate_duplicate_first(text: str) -> str:
    """Duplicate the first non-empty line — grader's dedup check should fire."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return text + "_"
    return "\n".join([lines[0], *lines]) + "\n"


NEGATIVE_CASES = [
    NegativeCase(
        name="empty",
        mutate=_mutate_empty,
        # Issue #185: after the fix the rejection message reads
        # "output artifact is empty but N unreachable function(s) were expected"
        # — still contains "empty", so the substring remains correct.
        expected_substring="empty",
    ),
    NegativeCase(
        name="truncated_half",
        mutate=_mutate_truncate_half,
        # Truncating mid-line yields a JSON parse error on that row.
        expected_substring="",
    ),
    NegativeCase(
        name="renamed_function_key",
        mutate=_mutate_rename_function_key,
        expected_substring="missing 'function'",
    ),
    NegativeCase(
        name="renamed_one_function_value",
        mutate=_mutate_rename_one_function,
        expected_substring="missing",
    ),
    NegativeCase(
        name="duplicated_function",
        mutate=_mutate_duplicate_first,
        expected_substring="duplicate",
    ),
    NegativeCase(
        name="drop_module_field",
        mutate=_mutate_drop_module,
        # Locked in by issue #166: grader now requires a ``module`` key on
        # every line.
        expected_substring="module",
        notes="issue #166 — locks 'module' key requirement",
    ),
    NegativeCase(
        name="wrong_module_value",
        mutate=_mutate_wrong_module,
        # Locked in by issue #166: grader now validates ``module`` against
        # the file each function was defined in.
        expected_substring="module",
        notes="issue #166 — locks 'module' value validation",
    ),
    NegativeCase(
        name="wrap_in_list",
        mutate=_mutate_wrap_in_list,
        expected_substring="",
    ),
]
