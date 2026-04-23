"""Public STRUCTURAL verifier for session_window. Shape only."""

from __future__ import annotations

import json
from pathlib import Path

_REQUIRED = {"user_id", "session_idx", "start_ts", "end_ts",
             "event_count", "total_duration_ms", "unique_pages"}


def verify(artifact_path: Path) -> None:
    artifact_path = Path(artifact_path)
    assert artifact_path.is_file(), f"artifact not found: {artifact_path}"

    raw = artifact_path.read_text()
    assert raw.strip(), "artifact is empty"

    seen: set[tuple[str, int]] = set()
    # Track max session_idx per user to verify monotonicity & 0-start later.
    max_idx_per_user: dict[str, int] = {}
    min_idx_per_user: dict[str, int] = {}
    count_per_user: dict[str, int] = {}

    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"line {lineno}: not valid JSON ({exc.msg})"
            ) from None
        assert isinstance(row, dict), f"line {lineno}: row must be an object"

        keys = set(row.keys())
        missing = _REQUIRED - keys
        extra = keys - _REQUIRED
        assert not missing, f"line {lineno}: missing {sorted(missing)}"
        assert not extra, f"line {lineno}: unexpected {sorted(extra)}"

        uid = row["user_id"]
        idx = row["session_idx"]
        assert isinstance(uid, str) and uid, f"line {lineno}: user_id must be non-empty string"
        assert isinstance(idx, int) and not isinstance(idx, bool), (
            f"line {lineno}: session_idx must be int"
        )
        assert idx >= 0, f"line {lineno}: session_idx must be >= 0"

        key = (uid, idx)
        assert key not in seen, f"line {lineno}: duplicate (user_id, session_idx) {key}"
        seen.add(key)

        start = row["start_ts"]
        end = row["end_ts"]
        assert isinstance(start, (int, float)) and not isinstance(start, bool), (
            f"line {lineno}: start_ts must be number"
        )
        assert isinstance(end, (int, float)) and not isinstance(end, bool), (
            f"line {lineno}: end_ts must be number"
        )
        assert float(end) >= float(start), (
            f"line {lineno}: end_ts {end} < start_ts {start}"
        )

        ev_count = row["event_count"]
        dur = row["total_duration_ms"]
        unique = row["unique_pages"]
        for name, val in (("event_count", ev_count), ("total_duration_ms", dur),
                          ("unique_pages", unique)):
            assert isinstance(val, int) and not isinstance(val, bool), (
                f"line {lineno}: {name} must be int"
            )
        assert ev_count >= 1, f"line {lineno}: event_count must be >= 1"
        assert dur >= 0, f"line {lineno}: total_duration_ms must be >= 0"
        assert 1 <= unique <= ev_count, (
            f"line {lineno}: unique_pages must be in [1, event_count]"
        )

        max_idx_per_user[uid] = max(max_idx_per_user.get(uid, -1), idx)
        min_idx_per_user[uid] = min(min_idx_per_user.get(uid, idx), idx)
        count_per_user[uid] = count_per_user.get(uid, 0) + 1

    assert seen, "artifact contains no rows"

    # Every user's session indices must be a 0..n-1 run.
    for uid, max_idx in max_idx_per_user.items():
        expected = max_idx + 1
        got = count_per_user[uid]
        assert got == expected, (
            f"user {uid}: session_idx goes 0..{max_idx} but only {got} rows "
            "(must be a contiguous 0-based run)"
        )
        assert min_idx_per_user[uid] == 0, (
            f"user {uid}: smallest session_idx is {min_idx_per_user[uid]}, must be 0"
        )
