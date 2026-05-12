"""Per-task negative cases for ``data_engineering__dedup_inventory_snapshots_medium``.

Locks down: column header order, sort order, the dedup-row-count rule (one
row per (warehouse_id, sku) composite key after uppercase normalization),
the warehouse-id uppercase requirement, the revision-as-integer rule
(empty must become ``0``), and the captured_at whitespace-stripping rule.
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
    lines = text.splitlines()
    if len(lines) <= 2:
        return text
    return "\n".join(lines[:-1]) + "\n"


def _mutate_duplicate_one_row(text: str) -> str:
    lines = text.splitlines()
    if len(lines) < 2:
        return text
    return text + lines[1] + "\n"


def _mutate_lowercase_warehouse(text: str) -> str:
    """Lowercase the ``warehouse_id`` cell of the first data row. Output
    must be uppercased per the prompt → grader's case check fires."""
    import csv as _csv
    import io as _io

    reader = _csv.reader(_io.StringIO(text))
    rows = list(reader)
    if len(rows) < 2:
        return text
    if rows[1]:
        rows[1][0] = rows[1][0].lower()
    buf = _io.StringIO()
    _csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue()


def _mutate_pad_captured_at(text: str) -> str:
    """Re-introduce whitespace into the first data row's ``captured_at``.
    Prompt requires stripping → structural and value check fire."""
    import csv as _csv
    import io as _io

    reader = _csv.reader(_io.StringIO(text))
    rows = list(reader)
    if len(rows) < 2 or len(rows[1]) < 4:
        return text
    rows[1][3] = "  " + rows[1][3] + "  "
    buf = _io.StringIO()
    _csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue()


def _mutate_revision_blank(text: str) -> str:
    """Replace the first data row's ``revision`` with the empty string.
    Empty must be normalized to ``0`` → integer check fires."""
    import csv as _csv
    import io as _io

    reader = _csv.reader(_io.StringIO(text))
    rows = list(reader)
    if len(rows) < 2 or len(rows[1]) < 5:
        return text
    rows[1][4] = ""
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
        name="duplicate_row",
        mutate=_mutate_duplicate_one_row,
        expected_substring="row count",
    ),
    NegativeCase(
        name="lowercase_warehouse",
        mutate=_mutate_lowercase_warehouse,
        expected_substring="uppercase",
    ),
    NegativeCase(
        name="padded_captured_at",
        mutate=_mutate_pad_captured_at,
        expected_substring="captured_at",
    ),
    NegativeCase(
        name="blank_revision",
        mutate=_mutate_revision_blank,
        expected_substring="revision",
    ),
]
