"""Public STRUCTURAL verifier for p95_latency_easy.

Checks shape/schema ONLY — never correctness. Per SCHEMA §4, a trivially-wrong
artifact (e.g. all p95 values = 0) MUST still pass verify(). Correctness lives
in grader/hidden.py.

Usage (agent-visible):

    from verify import verify
    verify(Path("output/p95.jsonl"))  # raises AssertionError on shape violation

This module is imported from the agent's scratch dir; it does not touch the
grader's hidden state.
"""

from __future__ import annotations

import json
from pathlib import Path

_REQUIRED_KEYS = {"endpoint", "p95_ms", "count"}


def verify(artifact_path: Path) -> None:
    """Raise AssertionError if ``artifact_path`` is not a valid-shape p95 artifact."""
    artifact_path = Path(artifact_path)
    assert artifact_path.is_file(), f"artifact not found: {artifact_path}"

    raw = artifact_path.read_text()
    assert raw.strip(), "artifact is empty"

    seen_endpoints: set[str] = set()
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
        missing = _REQUIRED_KEYS - keys
        extra = keys - _REQUIRED_KEYS
        assert not missing, f"line {lineno}: missing key(s) {sorted(missing)}"
        assert not extra, f"line {lineno}: unexpected key(s) {sorted(extra)}"

        ep = row["endpoint"]
        assert isinstance(ep, str) and ep, f"line {lineno}: endpoint must be a non-empty string"
        assert not ep.startswith("/health"), (
            f"line {lineno}: endpoint {ep!r} begins with /health — those rows "
            "must be excluded from the output"
        )

        p95 = row["p95_ms"]
        assert isinstance(p95, (int, float)) and not isinstance(p95, bool), (
            f"line {lineno}: p95_ms must be a number, got {type(p95).__name__}"
        )
        assert p95 >= 0, f"line {lineno}: p95_ms must be >= 0"

        count = row["count"]
        assert isinstance(count, int) and not isinstance(count, bool), (
            f"line {lineno}: count must be an integer, got {type(count).__name__}"
        )
        assert count >= 1, f"line {lineno}: count must be >= 1"

        assert ep not in seen_endpoints, (
            f"line {lineno}: duplicate endpoint {ep!r} — each endpoint must "
            "appear exactly once"
        )
        seen_endpoints.add(ep)

    assert seen_endpoints, "artifact contains no output rows"
