"""Per-task negative cases for ``data_processing__regression_detection``.

Issue #166 tightened the grader to require the three rows in **descending
order of regression_score** with ties broken lexicographically by endpoint
(matching what the prompt says). This module locks that behaviour in: a
reversed-rows mutation MUST be rejected.
"""

from __future__ import annotations

from swebench.artifact_negative import (
    NegativeCase,
    _mutate_empty,
    _mutate_reverse_lines,
    _mutate_truncate_half,
    _mutate_wrap_in_list,
)


def _mutate_drop_one_row(text: str) -> str:
    """Drop the last row — len-check fires (3 → 2)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return text + "_"
    return "\n".join(lines[:-1]) + "\n"


def _mutate_swap_endpoint(text: str) -> str:
    """Replace an endpoint with a known-not-in-top-3 placeholder."""
    return text.replace('"/api/payments"', '"/api/__BOGUS__"', 1)


def _mutate_off_by_one_score(text: str) -> str:
    """Bump one regression_score by 200ms (well outside REL_TOL)."""
    # Crude but deterministic: mutate the first numeric we see after
    # ``regression_score": ``.
    needle = '"regression_score": '
    idx = text.find(needle)
    if idx == -1:
        return text + "_"
    start = idx + len(needle)
    # Find the end of the number.
    end = start
    while end < len(text) and text[end] in "-0123456789.":
        end += 1
    try:
        original = float(text[start:end])
    except ValueError:
        return text + "_"
    new = round(original + 200.0, 3)
    return text[:start] + str(new) + text[end:]


NEGATIVE_CASES = [
    NegativeCase(
        name="empty",
        mutate=_mutate_empty,
        expected_substring="empty",
    ),
    NegativeCase(
        name="truncated_half",
        mutate=_mutate_truncate_half,
        # 3 → ~1 row; len-check fires.
        expected_substring="",
    ),
    NegativeCase(
        name="reversed_lines",
        mutate=_mutate_reverse_lines,
        # Locked in by issue #166: rows must be in descending order of
        # regression_score.
        expected_substring="order",
        notes="issue #166 — locks descending-order requirement",
    ),
    NegativeCase(
        name="dropped_row",
        mutate=_mutate_drop_one_row,
        expected_substring="3 rows",
    ),
    NegativeCase(
        name="swapped_endpoint",
        mutate=_mutate_swap_endpoint,
        expected_substring="incorrect endpoint",
    ),
    NegativeCase(
        name="off_by_one_score",
        mutate=_mutate_off_by_one_score,
        expected_substring="tolerance",
    ),
    NegativeCase(
        name="wrap_in_list",
        mutate=_mutate_wrap_in_list,
        # JSON parse error on the wrapping ``[``.
        expected_substring="",
    ),
]
