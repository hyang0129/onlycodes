"""Tests for ``swebench.artifact_audit`` — per-run grader-leak detector (issue #108)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from swebench.artifact_audit import (
    Fingerprints,
    MIN_COMBINED_LEN,
    audit_leak,
    extract_fingerprints,
    scan_text_for_fingerprints,
)
from swebench.artifact_models import ExecutionBudget, Task


SENTINEL_UUID = "deadbeef-0000-4000-8000-000000000001"


def _make_task(
    task_dir: Path,
    sentinel: str | None = SENTINEL_UUID,
    ref_lines: tuple[str, ...] = (
        '{"endpoint": "/api/v1/orders", "p95_ms": 221.027, "count": 819}',
        '{"endpoint": "/api/v1/checkout", "p95_ms": 808.95, "count": 378}',
        '{"endpoint": "/api/v1/catalog", "p95_ms": 308.5, "count": 545}',
    ),
) -> Task:
    (task_dir / "grader").mkdir(parents=True, exist_ok=True)
    hidden = "def grade(d):\n    return None\n"
    if sentinel is not None:
        hidden = f"# GRADER-SENTINEL: {sentinel}\n{hidden}"
    (task_dir / "grader" / "hidden.py").write_text(hidden)
    (task_dir / "grader" / "reference_output.jsonl").write_text(
        "\n".join(ref_lines) + "\n"
    )
    return Task(
        instance_id="test__audit",
        category="test",
        difficulty="easy",
        problem_statement="prompt.md",
        workspace_dir="workspace/",
        output_artifact="out.txt",
        hidden_grader="grader/hidden.py",
        reference_output="grader/reference_output.jsonl",
        execution_budget=ExecutionBudget(0, 0),
        task_dir=task_dir.resolve(),
    )


def test_extract_fingerprints_reads_sentinel(tmp_path: Path) -> None:
    task = _make_task(tmp_path / "t")
    fp = extract_fingerprints(task)
    assert fp.sentinel == SENTINEL_UUID
    assert len(fp.reference_lines) == 3


def test_extract_fingerprints_missing_sentinel(tmp_path: Path) -> None:
    task = _make_task(tmp_path / "t", sentinel=None)
    fp = extract_fingerprints(task)
    assert fp.sentinel is None
    assert len(fp.reference_lines) == 3


def test_extract_fingerprints_respects_min_combined_len(tmp_path: Path) -> None:
    """Short reference files should yield an empty line tuple."""
    task = _make_task(
        tmp_path / "t",
        ref_lines=("aa", "bb", "cc"),  # below MIN_LINE_LEN, all skipped
    )
    fp = extract_fingerprints(task)
    assert fp.reference_lines == ()


def test_extract_fingerprints_no_task_dir() -> None:
    task = Task(
        instance_id="x", category="x", difficulty="easy",
        problem_statement="p", workspace_dir="w",
        output_artifact="o", hidden_grader="g/h.py", reference_output="g/r",
        execution_budget=ExecutionBudget(0, 0), task_dir=None,
    )
    fp = extract_fingerprints(task)
    assert fp == Fingerprints(None, ())


def test_scan_detects_sentinel() -> None:
    fp = Fingerprints(sentinel=SENTINEL_UUID, reference_lines=())
    assert scan_text_for_fingerprints(f"...and then {SENTINEL_UUID} appeared", fp)


def test_scan_detects_reference_line() -> None:
    line = '{"endpoint": "/api/v1/orders", "p95_ms": 221.027, "count": 819}'
    fp = Fingerprints(sentinel=None, reference_lines=(line, "other", "third"))
    assert scan_text_for_fingerprints(f"tool result: {line}", fp)


def test_scan_clean_transcript_returns_false() -> None:
    fp = Fingerprints(sentinel=SENTINEL_UUID, reference_lines=("abc" * 10,))
    assert not scan_text_for_fingerprints("agent wrote some output.", fp)


def test_audit_leak_positive_sentinel_in_transcript(tmp_path: Path) -> None:
    task = _make_task(tmp_path / "t")
    jsonl = tmp_path / "agent.jsonl"
    jsonl.write_text(json.dumps({
        "type": "assistant",
        "content": f"peeked at hidden.py — saw {SENTINEL_UUID}",
    }) + "\n")
    assert audit_leak(task, jsonl) is True


def test_audit_leak_positive_reference_line(tmp_path: Path) -> None:
    task = _make_task(tmp_path / "t")
    jsonl = tmp_path / "agent.jsonl"
    leaked = '{"endpoint": "/api/v1/orders", "p95_ms": 221.027, "count": 819}'
    jsonl.write_text(
        json.dumps({"type": "tool_result", "content": f"read file: {leaked}"}) + "\n"
    )
    assert audit_leak(task, jsonl) is True


def test_audit_leak_clean_transcript(tmp_path: Path) -> None:
    task = _make_task(tmp_path / "t")
    jsonl = tmp_path / "agent.jsonl"
    jsonl.write_text(json.dumps({
        "type": "assistant",
        "content": "I wrote output/p95.jsonl based on my own computation.",
    }) + "\n")
    assert audit_leak(task, jsonl) is False


def test_audit_leak_missing_agent_jsonl(tmp_path: Path) -> None:
    task = _make_task(tmp_path / "t")
    assert audit_leak(task, tmp_path / "does-not-exist.jsonl") is False


def test_audit_leak_no_fingerprints_is_noop(tmp_path: Path) -> None:
    """If the grader has no sentinel and no usable reference lines, audit is a no-op."""
    task = _make_task(tmp_path / "t", sentinel=None, ref_lines=("aa", "bb"))
    jsonl = tmp_path / "agent.jsonl"
    jsonl.write_text("arbitrary text that happens to contain aa and bb\n")
    assert audit_leak(task, jsonl) is False


def test_min_combined_len_constant_is_reasonable() -> None:
    # Guard against accidental regression to a trivially-small threshold.
    assert MIN_COMBINED_LEN >= 40


def test_scan_matches_json_escaped_reference_line() -> None:
    """F-2 regression: ``_normalise`` must let a reference line containing
    double quotes match when those quotes are JSON-backslash-escaped inside
    ``agent.jsonl``. Removing ``_normalise`` would make this test fail
    without affecting any of the existing positive-path tests."""
    line = '{"endpoint": "/api/v1/orders", "p95_ms": 221.027, "count": 819}'
    fp = Fingerprints(sentinel=None, reference_lines=(line,))
    # Simulate how the line appears inside a stream-json record where inner
    # quotes are backslash-escaped (\" and \n). The raw substring does NOT
    # contain the needle verbatim — it only matches after ``_normalise``.
    haystack = (
        r'prefix {\"endpoint\": \"/api/v1/orders\", \"p95_ms\": 221.027, '
        r'\"count\": 819} suffix'
    )
    assert line not in haystack  # sanity: raw substring must differ
    assert scan_text_for_fingerprints(haystack, fp)


def test_scan_does_not_match_unrelated_escaped_content() -> None:
    """Paired negative for F-2: escaped content that is NOT the reference line
    must not match, even after normalisation."""
    line = '{"endpoint": "/api/v1/orders", "p95_ms": 221.027, "count": 819}'
    fp = Fingerprints(sentinel=None, reference_lines=(line,))
    haystack = r'{"type":"assistant","content":"I said \"hello world\" and moved on."}'
    assert not scan_text_for_fingerprints(haystack, fp)
