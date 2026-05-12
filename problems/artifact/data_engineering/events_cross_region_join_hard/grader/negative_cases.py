"""Per-task negative cases for ``data_engineering__events_cross_region_join_hard``.

Locks down header order, sort order across the three-key tuple,
timezone-corrected UTC timestamps, snake_case event type vocabulary,
and the drop-on-orphan / drop-on-unknown-event rules.
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


def _mutate_titlecase_event_type(text: str) -> str:
    """TitleCase the event_type in the first data row → not in the
    canonical snake_case vocabulary, grader rejects."""
    reader = _csv.reader(_io.StringIO(text))
    rows = list(reader)
    if len(rows) <= 1:
        return text
    rows[1][3] = rows[1][3].title()
    buf = _io.StringIO()
    _csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue()


def _mutate_strip_z_suffix(text: str) -> str:
    """Strip the trailing ``Z`` from the first data row's timestamp.
    Grader's ISO regex should reject."""
    reader = _csv.reader(_io.StringIO(text))
    rows = list(reader)
    if len(rows) <= 1:
        return text
    rows[1][0] = rows[1][0].rstrip("Z")
    buf = _io.StringIO()
    _csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue()


def _mutate_wrong_user_tier(text: str) -> str:
    """Flip the user_tier on a middle row to a different valid tier.
    Tests the foreign-key join correctness without disturbing sort
    order. Grader's value-disagreement check should fire."""
    reader = _csv.reader(_io.StringIO(text))
    rows = list(reader)
    if len(rows) < 4:
        return text
    mid = len(rows) // 2
    cur = rows[mid][2]
    rows[mid][2] = "pro" if cur != "pro" else "free"
    buf = _io.StringIO()
    _csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue()


def _mutate_extra_orphan_row(text: str) -> str:
    """Append a row referencing an orphan user id. Grader's row-count
    check should fire."""
    return text + "2026-01-01T00:00:00Z,999,free,login,us\n"


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
        name="titlecase_event_type",
        mutate=_mutate_titlecase_event_type,
        expected_substring="event_type",
    ),
    NegativeCase(
        name="strip_z_suffix",
        mutate=_mutate_strip_z_suffix,
        expected_substring="event_utc_ts",
    ),
    NegativeCase(
        name="wrong_user_tier",
        mutate=_mutate_wrong_user_tier,
        # Wrong tier from the users.csv join → value-disagreement check.
        expected_substring="disagrees",
    ),
    NegativeCase(
        name="extra_orphan_row",
        mutate=_mutate_extra_orphan_row,
        expected_substring="row count",
    ),
]
