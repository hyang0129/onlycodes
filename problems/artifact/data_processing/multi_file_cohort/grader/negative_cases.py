"""Per-task negative cases for ``data_processing__multi_file_cohort``.

The prompt requires the output rows to be sorted in **descending order by
total_revenue**, but the current grader only checks the *set* of product_ids,
not the row order. A reversed reference output therefore slips through the
grader today; that's the bug issue #171 calls out as
``multi_file_cohort order``. The ``reversed_lines`` case below is annotated
``currently_caught=False`` so the negative gate prints a WARNING for it
without failing CI; once the grader is updated to enforce ordering (tracked
under the prompt-vs-grader-alignment issue), flip it to ``True``.

Other cases here are mutations that the current grader DOES correctly catch
— they document the existing safety net.
"""

from __future__ import annotations

from swebench.artifact_negative import (
    NegativeCase,
    _mutate_empty,
    _mutate_rename_one_field,
    _mutate_reverse_lines,
    _mutate_truncate_half,
    _mutate_wrap_in_list,
)


def _mutate_drop_one_row(text: str) -> str:
    """Drop the last non-empty row. Top-5 becomes top-4 → grader's len check fires."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) <= 1:
        return ""
    return "\n".join(lines[:-1]) + "\n"


def _mutate_swap_pid(text: str) -> str:
    """Replace one product_id with a known-not-in-top-5 placeholder.

    Keeps the row count and JSON shape intact so the grader has to do a
    set-equality check against the reference pids, not just a structural
    pass.
    """
    return text.replace('"P023"', '"PXXX"', 1)


NEGATIVE_CASES = [
    NegativeCase(
        name="empty",
        mutate=_mutate_empty,
        # Empty file is produced (just empty content) → row-count check fires.
        expected_substring="5 entries",
    ),
    NegativeCase(
        name="truncated_half",
        mutate=_mutate_truncate_half,
        # Truncating mid-line yields a JSON parse error.
        expected_substring="could not parse",
    ),
    NegativeCase(
        name="reversed_lines",
        mutate=_mutate_reverse_lines,
        # PROMPT-VS-GRADER ALIGNMENT BUG: the prompt says "descending order"
        # but the grader does set-equality on product_ids without checking
        # row order. Today the grader returns passed=True on this mutation;
        # ``check_grader_negative`` will print WARNING and continue. Flip
        # ``currently_caught=True`` once the grader checks order.
        expected_substring="order",
        currently_caught=False,
        notes="issue #171 — multi_file_cohort missing descending-order check",
    ),
    NegativeCase(
        name="renamed_required_field",
        mutate=_mutate_rename_one_field,
        expected_substring="missing required keys",
    ),
    NegativeCase(
        name="wrong_pid",
        mutate=_mutate_swap_pid,
        expected_substring="wrong top-5",
    ),
    NegativeCase(
        name="dropped_row",
        mutate=_mutate_drop_one_row,
        expected_substring="5 entries",
    ),
    NegativeCase(
        name="wrap_in_list",
        mutate=_mutate_wrap_in_list,
        # Wrapping in [] makes line-by-line JSON parsing fail on the open
        # bracket "[".
        expected_substring="",  # any rejection is fine
    ),
]
