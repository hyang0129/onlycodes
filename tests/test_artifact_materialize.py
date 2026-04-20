"""Tests for swebench.artifact_materialize (no-leak invariant)."""

from __future__ import annotations

from pathlib import Path

import pytest

from swebench.artifact_materialize import (
    MaterializationError,
    materialize,
    scratch_dir_for,
)
from swebench.artifact_models import ExecutionBudget, Task


def _make_task(task_dir: Path, with_grader: bool = True) -> Task:
    (task_dir / "workspace").mkdir(parents=True, exist_ok=True)
    (task_dir / "workspace" / "input.txt").write_text("hello\n")
    (task_dir / "workspace" / "sub").mkdir(exist_ok=True)
    (task_dir / "workspace" / "sub" / "nested.txt").write_text("deep\n")
    if with_grader:
        (task_dir / "grader").mkdir(exist_ok=True)
        (task_dir / "grader" / "hidden.py").write_text("def grade(d): ...")
        (task_dir / "grader" / "reference_output.txt").write_text("secret\n")
    return Task(
        instance_id="test_fixture__trivial",
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


def test_materialize_copies_workspace(tmp_path: Path) -> None:
    task = _make_task(tmp_path / "task")
    scratch = tmp_path / "scratch"
    materialize(task, scratch)
    assert (scratch / "input.txt").read_text() == "hello\n"
    assert (scratch / "sub" / "nested.txt").read_text() == "deep\n"


def test_materialize_never_copies_grader(tmp_path: Path) -> None:
    task = _make_task(tmp_path / "task")
    scratch = tmp_path / "scratch"
    materialize(task, scratch)
    # Absolute invariant: no hidden.py, no reference_output* anywhere in scratch.
    assert not any(scratch.rglob("hidden.py"))
    assert not any(scratch.rglob("reference_output*"))
    assert not (scratch / "grader").exists()


def test_materialize_detects_leak(tmp_path: Path) -> None:
    """If a task author accidentally put a grader file inside workspace/,
    the post-copy scan must flag it."""
    task = _make_task(tmp_path / "task")
    (task.task_dir / "workspace" / "reference_output.jsonl").write_text("leaked\n")
    scratch = tmp_path / "scratch"
    with pytest.raises(MaterializationError, match="No-leak invariant"):
        materialize(task, scratch)


def test_materialize_detects_hidden_py_leak(tmp_path: Path) -> None:
    task = _make_task(tmp_path / "task")
    (task.task_dir / "workspace" / "hidden.py").write_text("def grade(d): ...")
    scratch = tmp_path / "scratch"
    with pytest.raises(MaterializationError):
        materialize(task, scratch)


def test_scratch_dir_for_layout() -> None:
    results = Path("/r")
    p = scratch_dir_for(results, "cat__slug", "code_only", 3)
    assert p == Path("/r/cat__slug/code_only/run3/scratch")
