"""Per-task negative cases for ``data_engineering__dedup_event_log_priority_hard``.

Locks down: column header order, sort order, the dedup-row-count rule (one
row per (tenant_id, entity_id, event_kind) composite key after dropping
superseded events), the version-as-integer rule (no ``v`` prefix), the
canonical-timestamp format with 6-digit microseconds and trailing ``Z``,
and the status-precedence ladder.
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


def _mutate_v_prefix_version(text: str) -> str:
    """Re-add the ``v`` prefix on the first row's version. Output must be
    a plain integer → grader's version check fires."""
    import csv as _csv
    import io as _io

    reader = _csv.reader(_io.StringIO(text))
    rows = list(reader)
    if len(rows) < 2 or len(rows[1]) < 6:
        return text
    rows[1][5] = "v" + rows[1][5]
    buf = _io.StringIO()
    _csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue()


def _mutate_millis_only_ts(text: str) -> str:
    """Truncate the first row's ``received_at_utc`` to millisecond
    precision (3 decimals instead of 6). Output must be 6-digit micros →
    grader's ts-shape check fires."""
    import csv as _csv
    import io as _io

    reader = _csv.reader(_io.StringIO(text))
    rows = list(reader)
    if len(rows) < 2 or len(rows[1]) < 7:
        return text
    ts = rows[1][6]
    if "." in ts and ts.endswith("Z") and len(ts.split(".")[-1]) == 7:
        # Replace .ffffffZ with .fffZ.
        head, frac = ts.rsplit(".", 1)
        rows[1][6] = head + "." + frac[:3] + "Z"
        buf = _io.StringIO()
        _csv.writer(buf, lineterminator="\n").writerows(rows)
        return buf.getvalue()
    return text


def _mutate_pick_lower_status(text: str) -> str:
    """Replace the first row's ``status`` with one strictly lower in the
    precedence ladder (``COMMITTED`` → ``FAILED``). The dedup winner
    cannot be ``FAILED`` if any other replica had any other status, so
    the value-disagreement check fires (or, in the rare case the
    ``status`` happens to already be the winner regardless, the row count
    check still won't fire — but the per-row status comparison will)."""
    import csv as _csv
    import io as _io

    reader = _csv.reader(_io.StringIO(text))
    rows = list(reader)
    if len(rows) < 2 or len(rows[1]) < 5:
        return text
    rows[1][4] = "FAILED"
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
        name="v_prefix_version",
        mutate=_mutate_v_prefix_version,
        expected_substring="version",
    ),
    NegativeCase(
        name="millis_only_timestamp",
        mutate=_mutate_millis_only_ts,
        expected_substring="received_at_utc",
    ),
    NegativeCase(
        name="lower_status",
        mutate=_mutate_pick_lower_status,
        expected_substring="disagrees",
    ),
]
