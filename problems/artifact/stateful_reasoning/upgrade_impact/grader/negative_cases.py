"""Per-task negative cases for ``stateful_reasoning__upgrade_impact``.

The grader contains an "output artifact is empty" early-exit (lines 100-101
of grader/hidden.py). When the *correct* answer is empty (i.e. zero
conflicts after the upgrade), an agent that correctly produces an empty
artifact is rejected by that early-exit instead of being graded by the
correctness check. The reference output for this task happens to have three
conflicts, so the bug doesn't surface against ``reference_output.jsonl`` —
that's the ``upgrade_impact empty-output`` bug called out in issue #171.

We can't fully exercise that bug with a pure mutation of the reference
output (it requires constructing an alternate workspace where the correct
answer is empty). What we CAN do is document the bug and add the regular
suite of mutations so the rest of the grader's safety net is exercised.
The empty-output regression test belongs in a future PR alongside the
grader fix.
"""

from __future__ import annotations

import json

from swebench.artifact_negative import (
    NegativeCase,
    _mutate_empty,
    _mutate_truncate_half,
    _mutate_wrap_in_list,
)


def _mutate_drop_one_package(text: str) -> str:
    """Drop the first reported conflict — set diverges → grader fails."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return text + "_"
    return "\n".join(lines[1:]) + "\n"


def _mutate_extra_bogus_package(text: str) -> str:
    """Append a bogus package name not in the dependency graph."""
    return text + json.dumps({"package": "PHANTOM_PACKAGE"}) + "\n"


def _mutate_rename_package_key(text: str) -> str:
    return text.replace('"package":', '"pkg":')


def _mutate_swap_package_for_constraint(text: str) -> str:
    """Replace the first 'package' value with a guaranteed-wrong name.

    Keeps row count and shape identical — exercises the set-equality check.
    """
    return text.replace('"api-gateway"', '"NOT_A_REAL_PACKAGE"', 1)


def _mutate_duplicate_package(text: str) -> str:
    """Duplicate the first conflict line — dedup check should fire."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return text + "_"
    return "\n".join([lines[0], *lines]) + "\n"


NEGATIVE_CASES = [
    NegativeCase(
        name="empty",
        mutate=_mutate_empty,
        # Today the grader's structural early-exit catches this. After the
        # empty-output false-negative fix lands, the rejection should come
        # from the correctness check instead — at that point flip
        # ``expected_substring`` to e.g. "missing".
        expected_substring="empty",
    ),
    NegativeCase(
        name="truncated_half",
        mutate=_mutate_truncate_half,
        expected_substring="",  # JSON parse error or missing-package
    ),
    NegativeCase(
        name="renamed_package_key",
        mutate=_mutate_rename_package_key,
        expected_substring="missing 'package'",
    ),
    NegativeCase(
        name="dropped_one_package",
        mutate=_mutate_drop_one_package,
        expected_substring="missing",
    ),
    NegativeCase(
        name="extra_bogus_package",
        mutate=_mutate_extra_bogus_package,
        expected_substring="incorrect package",
    ),
    NegativeCase(
        name="swap_package_name",
        mutate=_mutate_swap_package_for_constraint,
        expected_substring="",  # missing AND incorrect both fire
    ),
    NegativeCase(
        name="duplicate_package",
        mutate=_mutate_duplicate_package,
        expected_substring="duplicate",
    ),
    NegativeCase(
        name="wrap_in_list",
        mutate=_mutate_wrap_in_list,
        expected_substring="",
    ),
]
