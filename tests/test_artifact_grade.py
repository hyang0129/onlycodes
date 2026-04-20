"""Tests for swebench.artifact_grade (subprocess-based grader invocation)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from swebench.artifact_grade import GraderInvocationError, invoke_grader
from swebench.artifact_models import ExecutionBudget, GradeResult, Task


def _write_task_with_grader(task_dir: Path, grader_body: str) -> Task:
    (task_dir / "workspace").mkdir(parents=True, exist_ok=True)
    (task_dir / "grader").mkdir(parents=True, exist_ok=True)
    (task_dir / "grader" / "hidden.py").write_text(textwrap.dedent(grader_body))
    (task_dir / "grader" / "reference_output.txt").write_text("ref")
    return Task(
        instance_id="test_fixture__grader",
        category="test_fixture",
        difficulty="easy",
        problem_statement="prompt.md",
        workspace_dir="workspace/",
        output_artifact="out.txt",
        hidden_grader="grader/hidden.py",
        reference_output="grader/reference_output.txt",
        execution_budget=ExecutionBudget(0, 0),
        task_dir=task_dir.resolve(),
    )


def test_grader_pass(tmp_path: Path) -> None:
    task = _write_task_with_grader(tmp_path / "task", """
        from dataclasses import dataclass

        @dataclass
        class R:
            passed: bool
            score: float
            detail: str

        def grade(scratch_dir):
            return R(True, 1.0, "looks good")
    """)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    result = invoke_grader(task, scratch)
    assert isinstance(result, GradeResult)
    assert result.passed is True
    assert result.score == 1.0
    assert result.detail == "looks good"


def test_grader_fail_reports_detail(tmp_path: Path) -> None:
    task = _write_task_with_grader(tmp_path / "task", """
        class R:
            def __init__(self, p, s, d):
                self.passed, self.score, self.detail = p, s, d

        def grade(scratch_dir):
            return R(False, 0.25, "missing key foo")
    """)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    result = invoke_grader(task, scratch)
    assert result.passed is False
    assert result.score == 0.25
    assert "missing key foo" in result.detail


def test_grader_reads_scratch_dir(tmp_path: Path) -> None:
    """Verify the grader actually receives the scratch_dir path as a Path."""
    task = _write_task_with_grader(tmp_path / "task", """
        from pathlib import Path

        class R:
            passed = False
            score = 0.0
            detail = ""

        def grade(scratch_dir):
            assert isinstance(scratch_dir, Path)
            artifact = scratch_dir / "answer.txt"
            r = R()
            r.passed = artifact.exists() and artifact.read_text().strip() == "42"
            r.score = 1.0 if r.passed else 0.0
            r.detail = f"artifact={'found' if artifact.exists() else 'missing'}"
            return r
    """)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "answer.txt").write_text("42\n")
    result = invoke_grader(task, scratch)
    assert result.passed is True
    assert result.score == 1.0


def test_grader_exception_surfaces_as_invocation_error(tmp_path: Path) -> None:
    task = _write_task_with_grader(tmp_path / "task", """
        def grade(scratch_dir):
            raise RuntimeError("boom")
    """)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(GraderInvocationError, match="boom"):
        invoke_grader(task, scratch)


def test_grader_missing_raises(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    (task_dir / "workspace").mkdir(parents=True)
    (task_dir / "grader").mkdir(parents=True)
    # Deliberately no hidden.py
    (task_dir / "grader" / "reference_output.txt").write_text("")
    task = Task(
        instance_id="test_fixture__nograder",
        category="test_fixture",
        difficulty="easy",
        problem_statement="prompt.md",
        workspace_dir="workspace/",
        output_artifact="out.txt",
        hidden_grader="grader/hidden.py",
        reference_output="grader/reference_output.txt",
        execution_budget=ExecutionBudget(0, 0),
        task_dir=task_dir.resolve(),
    )
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(GraderInvocationError, match="grader/hidden.py not found"):
        invoke_grader(task, scratch)
