"""Offline tests for artifact-benchmark parity in the pathology pipeline.

Before this change, ``_discover_logs`` only globbed flat ``*_run*.jsonl``
files and ``_parse_log_ref`` only recognised the SWE-bench filename
shape. Artifact logs live at
``runs/artifact/<task>/<arm>/run<N>/agent.jsonl`` and were silently
dropped.

These tests exercise:
  - discovery walks the nested artifact layout
  - ``_parse_log_ref`` returns artifact arm names (``tool_rich`` / ``code_only``)
  - synthesized ``log_ref`` is ``<task>__<arm>__run<N>``
  - ``VALID_ARMS`` includes the artifact arm names
  - ``--stage mechanical --dry-run`` on a seeded artifact tree exits 0
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from swebench.analyze import analyze_command, registry
from swebench.analyze.run import (
    _discover_logs,
    _parse_log_ref,
    _synthesize_log_ref,
)


def test_valid_arms_includes_artifact_arms() -> None:
    assert "tool_rich" in registry.VALID_ARMS
    assert "code_only" in registry.VALID_ARMS
    # Legacy SWE-bench arms still accepted.
    assert "baseline" in registry.VALID_ARMS
    assert "onlycode" in registry.VALID_ARMS


def test_validate_subagent_output_accepts_artifact_arm() -> None:
    data = {
        "log_ref": "fake_task__code_only__run1",
        "arm": "code_only",
        "findings": [],
    }
    assert registry.validate_subagent_output(data) == []


def test_discover_logs_walks_artifact_layout(tmp_path: Path) -> None:
    # Seed nested artifact layout.
    base = tmp_path / "results_artifact"
    for arm in ("tool_rich", "code_only"):
        run_dir = base / "algorithmic__makespan" / arm / "run1"
        run_dir.mkdir(parents=True)
        (run_dir / "agent.jsonl").write_text(
            json.dumps({"type": "result", "num_turns": 1}) + "\n"
        )

    logs = _discover_logs(base)
    assert len(logs) == 2, f"expected 2 artifact logs, got: {logs}"
    for p in logs:
        assert p.name == "agent.jsonl"
        assert p.parent.name == "run1"


def test_discover_logs_excludes_analysis_dir(tmp_path: Path) -> None:
    base = tmp_path / "results_artifact"
    run_dir = base / "task__slug" / "tool_rich" / "run1"
    run_dir.mkdir(parents=True)
    (run_dir / "agent.jsonl").write_text("")

    # Create a spurious _analysis tree that should be skipped.
    bad = base / "_analysis" / "some_run" / "tool_rich" / "run1"
    bad.mkdir(parents=True)
    (bad / "agent.jsonl").write_text("")

    logs = _discover_logs(base)
    assert len(logs) == 1
    assert "_analysis" not in str(logs[0])


def test_discover_logs_handles_mixed_layout(tmp_path: Path) -> None:
    """Flat SWE-bench files and nested artifact trees can coexist."""
    base = tmp_path / "results_mixed"
    base.mkdir()
    flat = base / "django__django-16379_baseline_run1.jsonl"
    flat.write_text("")

    nested = base / "algorithmic__foo" / "code_only" / "run2"
    nested.mkdir(parents=True)
    (nested / "agent.jsonl").write_text("")

    logs = _discover_logs(base)
    names = {p.name for p in logs}
    assert "django__django-16379_baseline_run1.jsonl" in names
    assert "agent.jsonl" in names


def test_parse_log_ref_artifact_layout(tmp_path: Path) -> None:
    p = tmp_path / "data_processing__p95_latency" / "tool_rich" / "run3" / "agent.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text("")
    parsed = _parse_log_ref(p)
    assert parsed == ("data_processing__p95_latency", "tool_rich", 3)


def test_parse_log_ref_swebench_still_works(tmp_path: Path) -> None:
    p = tmp_path / "django__django-16379_baseline_run1.jsonl"
    p.write_text("")
    parsed = _parse_log_ref(p)
    assert parsed == ("django__django-16379", "baseline", 1)


def test_parse_log_ref_returns_none_for_unparseable(tmp_path: Path) -> None:
    p = tmp_path / "weird.jsonl"
    p.write_text("")
    assert _parse_log_ref(p) is None


def test_synthesize_log_ref_artifact_uses_task_arm_run_form(tmp_path: Path) -> None:
    """Synthesized log_ref embeds task, arm, and run with `__` separators.

    Note: artifact task IDs themselves contain `__` (per the
    `<category>__<slug>` convention in docs/SCHEMA_ARTIFACT.md), so the
    resulting log_ref has four `__`-delimited fields, not three. Downstream
    consumers must treat it as an opaque identifier and call
    ``_parse_log_ref`` on the original JSONL path to recover structure.
    """
    p = tmp_path / "algorithmic__makespan" / "code_only" / "run5" / "agent.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text("")
    parsed = _parse_log_ref(p)
    ref = _synthesize_log_ref(parsed, p)
    assert ref == "algorithmic__makespan__code_only__run5"


def test_synthesize_log_ref_swebench_uses_stem(tmp_path: Path) -> None:
    p = tmp_path / "django__django-16379_baseline_run1.jsonl"
    p.write_text("")
    parsed = _parse_log_ref(p)
    ref = _synthesize_log_ref(parsed, p)
    assert ref == "django__django-16379_baseline_run1"


# ---------------------------------------------------------------------------
# End-to-end CLI smoke
# ---------------------------------------------------------------------------


def _invoke(args: list[str]):
    runner = CliRunner()
    return runner.invoke(analyze_command, args, catch_exceptions=False)


def test_pathology_mechanical_dry_run_on_artifact_tree(tmp_path: Path) -> None:
    """``--stage mechanical --dry-run --results-dir results_artifact/`` succeeds."""
    base = tmp_path / "results_artifact"
    run_dir = base / "algorithmic__makespan" / "tool_rich" / "run1"
    run_dir.mkdir(parents=True)
    (run_dir / "agent.jsonl").write_text(
        json.dumps({"type": "result", "total_cost_usd": 0.0, "num_turns": 1}) + "\n"
    )

    result = _invoke([
        "pathology",
        "--results-dir", str(base),
        "--stage", "mechanical",
        "--dry-run",
        "--run-id", "art-test",
    ])
    assert result.exit_code == 0, result.output
    # Discovery must have found the artifact log.
    assert "agent.jsonl" in result.output or "would extract" in result.output
    # No sidecars in dry-run.
    assert not (base / "_analysis" / "art-test").exists()
