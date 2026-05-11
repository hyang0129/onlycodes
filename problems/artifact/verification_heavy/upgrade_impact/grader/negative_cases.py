"""Per-task negative cases for ``verification_heavy__upgrade_impact``.

Issue #185 fixed the empty-output false-negative in grader/hidden.py.  The
grader now computes the reference *before* the empty-output check, so an empty
output against a non-empty reference is rejected with "output artifact is empty
but N conflict(s) were expected" instead of the old bare "output artifact is
empty".  Since the reference for this task is non-empty (three conflicts), the
empty-output mutation still triggers a rejection — ``expected_substring="empty"``
remains correct.

The positive empty-output case (a packages.json where the upgrade causes zero
conflicts → empty output must PASS) is exercised by the unit test added in
issue #185 (``tests/test_artifact_grade.py::test_upgrade_impact_empty_output_pass``).
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
        # The reference for this task has three conflicts, so empty output is
        # always wrong.  Issue #185 changed the rejection message to include
        # "but N conflict(s) were expected" — it still contains "empty".
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
