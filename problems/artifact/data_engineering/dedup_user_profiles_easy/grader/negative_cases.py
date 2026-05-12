"""Per-task negative cases for ``data_engineering__dedup_user_profiles_easy``.

Locks down: column header order, sort order, the dedup-row-count rule (one
row per (tenant, user_id) composite key), and that empty emails stay empty.
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
    """Drop one valid data row → row count short → grader fires."""
    lines = text.splitlines()
    if len(lines) <= 2:
        return text
    return "\n".join(lines[:-1]) + "\n"


def _mutate_duplicate_one_row(text: str) -> str:
    """Append a duplicate of the first data row → row count over → grader fires.

    The duplicate is byte-identical, so it shares the same ``(tenant, user_id)``
    pair — exactly the kind of error the dedup task is meant to prevent."""
    lines = text.splitlines()
    if len(lines) < 2:
        return text
    return text + lines[1] + "\n"


def _mutate_pick_older_row(text: str) -> str:
    """Roll back the first data row's ``last_updated`` and ``version`` to
    values that are *older* than what the dedup winner would actually be.
    Picking an older snapshot for a key violates the latest-wins rule."""
    import csv as _csv
    import io as _io

    reader = _csv.reader(_io.StringIO(text))
    rows = list(reader)
    if len(rows) < 2:
        return text
    # Columns: tenant, user_id, name, email, version, last_updated
    VERSION_IDX = 4
    TS_IDX = 5
    r = rows[1]
    if len(r) <= TS_IDX:
        return text
    # Make version smaller and timestamp earlier.
    try:
        v = int(r[VERSION_IDX])
        r[VERSION_IDX] = str(max(0, v - 1))
    except ValueError:
        pass
    # Replace timestamp with one that is guaranteed older than any window in
    # the generator (Jan 2020 < Apr 2026).
    r[TS_IDX] = "2020-01-01T00:00:00Z"
    buf = _io.StringIO()
    _csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue()


def _mutate_email_null_string(text: str) -> str:
    """Replace an empty ``email`` cell with the literal string ``NULL``.
    Empty-as-empty is required → grader's value-disagrees check fires."""
    import csv as _csv
    import io as _io

    reader = _csv.reader(_io.StringIO(text))
    rows = list(reader)
    if len(rows) <= 1:
        return text
    EMAIL_IDX = 3
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
        name="duplicate_row",
        mutate=_mutate_duplicate_one_row,
        expected_substring="row count",
    ),
    NegativeCase(
        name="picked_older_row",
        mutate=_mutate_pick_older_row,
        expected_substring="disagrees",
    ),
    NegativeCase(
        name="email_as_null_string",
        mutate=_mutate_email_null_string,
        expected_substring="disagrees",
    ),
]
