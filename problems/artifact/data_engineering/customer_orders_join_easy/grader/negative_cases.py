"""Per-task negative cases for ``data_engineering__customer_orders_join_easy``.

The prompt nails down (a) the column header order, (b) the sort order
``(order_date asc, order_id asc)``, and (c) the ``amount_usd`` 2-decimal
format. The custom mutations below lock each of those down.
"""

from __future__ import annotations

from swebench.artifact_negative import (
    NegativeCase,
    _mutate_empty,
    _mutate_reverse_lines,
    _mutate_truncate_half,
    _mutate_wrap_in_list,
)


def _mutate_drop_header(text: str) -> str:
    """Remove the header row entirely. Grader's header check should fire."""
    lines = text.splitlines()
    if len(lines) <= 1:
        return ""
    return "\n".join(lines[1:]) + "\n"


def _mutate_reorder_header(text: str) -> str:
    """Swap two header columns while keeping data rows aligned to the
    original order. Grader's exact-header check should fire."""
    lines = text.splitlines()
    if not lines:
        return text
    cols = lines[0].split(",")
    # swap order_date and amount_usd
    cols[2], cols[3] = cols[3], cols[2]
    lines[0] = ",".join(cols)
    return "\n".join(lines) + "\n"


def _mutate_reverse_data_rows(text: str) -> str:
    """Reverse the data rows while keeping the header in place. The
    grader's sort-order check should fire: rows are no longer in
    ascending order by (order_date, order_id)."""
    lines = text.splitlines()
    if len(lines) <= 2:
        return text
    header, *data = lines
    return "\n".join([header] + list(reversed(data))) + "\n"


def _mutate_three_decimals(text: str) -> str:
    """Pad amount_usd to 3 decimal places in the first data row. The
    prompt requires exactly 2 decimal places, so the grader should reject."""
    lines = text.splitlines()
    if len(lines) < 2:
        return text
    parts = lines[1].split(",")
    if len(parts) >= 4 and "." in parts[3]:
        parts[3] = parts[3] + "0"
        lines[1] = ",".join(parts)
    return "\n".join(lines) + "\n"


NEGATIVE_CASES = [
    NegativeCase(
        name="empty",
        mutate=_mutate_empty,
        expected_substring="empty",
    ),
    NegativeCase(
        name="truncated_half",
        mutate=_mutate_truncate_half,
        # Truncation usually breaks the row count or trailing row's field count.
        expected_substring="",
    ),
    NegativeCase(
        name="reversed_lines",
        mutate=_mutate_reverse_lines,
        # Reversing puts the header at the bottom → header check fires.
        expected_substring="header",
    ),
    NegativeCase(
        name="wrap_in_list",
        mutate=_mutate_wrap_in_list,
        # Wrapping yields a malformed CSV; csv.reader returns junk rows.
        expected_substring="",
    ),
    NegativeCase(
        name="dropped_header",
        mutate=_mutate_drop_header,
        expected_substring="header",
    ),
    NegativeCase(
        name="reordered_header",
        mutate=_mutate_reorder_header,
        expected_substring="header",
    ),
    NegativeCase(
        name="three_decimals",
        mutate=_mutate_three_decimals,
        expected_substring="2 decimal",
    ),
    NegativeCase(
        name="reversed_data_rows",
        mutate=_mutate_reverse_data_rows,
        expected_substring="sorted",
    ),
]
