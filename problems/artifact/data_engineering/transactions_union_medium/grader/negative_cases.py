"""Per-task negative cases for ``data_engineering__transactions_union_medium``.

Locks down header order, sort order, drop-rule row count, currency
normalization, and the 2-decimal amount format.
"""

from __future__ import annotations

import csv as _csv
import io as _io

from swebench.artifact_negative import (
    NegativeCase,
    _mutate_empty,
    _mutate_reverse_lines,
    _mutate_truncate_half,
    _mutate_wrap_in_list,
)


def _mutate_drop_header(text: str) -> str:
    lines = text.splitlines()
    if len(lines) <= 1:
        return ""
    return "\n".join(lines[1:]) + "\n"


def _mutate_reverse_data_rows(text: str) -> str:
    lines = text.splitlines()
    if len(lines) <= 2:
        return text
    header, *data = lines
    return "\n".join([header] + list(reversed(data))) + "\n"


def _mutate_drop_one_row(text: str) -> str:
    lines = text.splitlines()
    if len(lines) <= 2:
        return text
    return "\n".join(lines[:-1]) + "\n"


def _mutate_three_decimals(text: str) -> str:
    lines = text.splitlines()
    if len(lines) < 2:
        return text
    parts = lines[1].split(",")
    if len(parts) >= 3 and "." in parts[2]:
        parts[2] = parts[2] + "0"
        lines[1] = ",".join(parts)
    return "\n".join(lines) + "\n"


def _mutate_lowercase_currency(text: str) -> str:
    """Lowercase the currency_code on the first data row. The prompt
    requires uppercase ISO codes."""
    reader = _csv.reader(_io.StringIO(text))
    rows = list(reader)
    if len(rows) <= 1:
        return text
    rows[1][3] = rows[1][3].lower()
    buf = _io.StringIO()
    _csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue()


def _mutate_keep_unknown_currency_row(text: str) -> str:
    """Append an extra row with an unknown currency. The grader's row
    count check should catch it (the row should have been dropped)."""
    return text + "TX-EXTRA,2026-01-01,99.99,JPY\n"


NEGATIVE_CASES = [
    NegativeCase(name="empty", mutate=_mutate_empty, expected_substring="empty"),
    NegativeCase(name="truncated_half", mutate=_mutate_truncate_half, expected_substring=""),
    NegativeCase(
        name="reversed_lines",
        mutate=_mutate_reverse_lines,
        expected_substring="header",
    ),
    NegativeCase(name="wrap_in_list", mutate=_mutate_wrap_in_list, expected_substring=""),
    NegativeCase(
        name="dropped_header",
        mutate=_mutate_drop_header,
        expected_substring="header",
    ),
    NegativeCase(
        name="reversed_data_rows",
        mutate=_mutate_reverse_data_rows,
        expected_substring="sorted",
    ),
    NegativeCase(
        name="dropped_row",
        mutate=_mutate_drop_one_row,
        expected_substring="row count",
    ),
    NegativeCase(
        name="three_decimals",
        mutate=_mutate_three_decimals,
        expected_substring="2 decimal",
    ),
    NegativeCase(
        name="lowercase_currency",
        mutate=_mutate_lowercase_currency,
        expected_substring="USD/EUR/GBP",
    ),
    NegativeCase(
        name="extra_unknown_currency_row",
        mutate=_mutate_keep_unknown_currency_row,
        expected_substring="row count",
    ),
]
