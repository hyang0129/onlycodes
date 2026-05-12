"""Per-task negative cases for ``data_engineering__orders_lookup_join_medium``.

Locks down: column header order, sort order, the orphan-dropping
requirement (no extra rows), the 2-decimal format on monetary fields,
and the empty-email-as-empty-string convention.
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
    """Drop one valid data row → row count short by one → grader's
    row-count check should fire (output is missing a non-orphan)."""
    lines = text.splitlines()
    if len(lines) <= 2:
        return text
    return "\n".join(lines[:-1]) + "\n"


def _mutate_add_orphan_row(text: str) -> str:
    """Append a row that looks structurally valid but represents an
    order that should have been dropped as an orphan. Row count check
    should fire (one extra row beyond the expected non-orphan set)."""
    lines = text.splitlines()
    if not lines:
        return text
    # Pick the first data row and copy it with a benign mutation. The grader
    # only checks count + per-row equality after sort, so extra rows fail.
    extra = lines[1] if len(lines) >= 2 else ""
    return text + extra + "\n"


def _mutate_three_decimals(text: str) -> str:
    """Pad unit_price to 3 decimal places in the first data row."""
    lines = text.splitlines()
    if len(lines) < 2:
        return text
    parts = lines[1].split(",")
    # unit_price is column index 7 in EXPECTED_COLUMNS
    if len(parts) >= 8 and "." in parts[7]:
        parts[7] = parts[7] + "0"
        lines[1] = ",".join(parts)
    return "\n".join(lines) + "\n"


def _mutate_email_null_string(text: str) -> str:
    """Replace the first empty ``customer_email`` cell with the literal
    string ``NULL``. The prompt requires empty-as-empty, so the grader's
    per-row value-disagreement check should fire."""
    import csv as _csv
    import io as _io

    reader = _csv.reader(_io.StringIO(text))
    rows = list(reader)
    if len(rows) <= 1:
        return text
    EMAIL_IDX = 3  # customer_email column
    for r in rows[1:]:
        if len(r) > EMAIL_IDX and r[EMAIL_IDX] == "":
            r[EMAIL_IDX] = "NULL"
            break
    buf = _io.StringIO()
    _csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue()


NEGATIVE_CASES = [
    NegativeCase(name="empty", mutate=_mutate_empty, expected_substring="empty"),
    NegativeCase(
        name="truncated_half",
        mutate=_mutate_truncate_half,
        expected_substring="",
    ),
    NegativeCase(
        name="reversed_lines",
        mutate=_mutate_reverse_lines,
        expected_substring="header",
    ),
    NegativeCase(
        name="wrap_in_list",
        mutate=_mutate_wrap_in_list,
        expected_substring="",
    ),
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
        name="extra_orphan_row",
        mutate=_mutate_add_orphan_row,
        expected_substring="row count",
    ),
    NegativeCase(
        name="three_decimals",
        mutate=_mutate_three_decimals,
        expected_substring="2 decimal",
    ),
    NegativeCase(
        name="email_as_null_string",
        mutate=_mutate_email_null_string,
        # Empty email should remain empty — replacing with ``NULL`` is a
        # value disagreement, which the grader flags as "disagrees".
        expected_substring="disagrees",
    ),
]
