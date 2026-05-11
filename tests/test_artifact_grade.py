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


# ─────────────────────────────────────────────────────────────────────────────
# Issue #185 regression tests — empty-output positive cases
#
# Both unreachable_functions and upgrade_impact graders had an early-exit that
# rejected empty output unconditionally.  These tests exercise the case where
# the correct answer IS empty: the grader must return passed=True, score=1.0.
# ─────────────────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_task_from_grader_file(
    tmp_task_dir: Path,
    grader_src: Path,
    ref_src: Path,
    instance_id: str,
    category: str,
    output_artifact: str,
) -> Task:
    """Copy a real grader file into a temp task dir and build a Task object."""
    import shutil

    tmp_task_dir.mkdir(parents=True, exist_ok=True)
    (tmp_task_dir / "workspace").mkdir(exist_ok=True)
    (tmp_task_dir / "grader").mkdir(exist_ok=True)
    shutil.copy(grader_src, tmp_task_dir / "grader" / "hidden.py")
    shutil.copy(ref_src, tmp_task_dir / "grader" / ref_src.name)
    return Task(
        instance_id=instance_id,
        category=category,
        difficulty="medium",
        problem_statement="prompt.md",
        workspace_dir="workspace/",
        output_artifact=output_artifact,
        hidden_grader="grader/hidden.py",
        reference_output=f"grader/{ref_src.name}",
        execution_budget=ExecutionBudget(0, 0),
        task_dir=tmp_task_dir.resolve(),
    )


def test_unreachable_functions_empty_output_pass(tmp_path: Path) -> None:
    """Issue #185: when all functions are reachable, empty output must PASS.

    Constructs a minimal src/ tree where every function is directly or
    transitively called from main(), so the unreachable set is empty.
    An agent that correctly produces an empty output/unreachable.jsonl should
    receive passed=True, score=1.0 — not the old false-negative FAIL.
    """
    import shutil

    grader_src = (
        _REPO_ROOT
        / "problems/artifact/verification_heavy/unreachable_functions/grader/hidden.py"
    )
    ref_src = (
        _REPO_ROOT
        / "problems/artifact/verification_heavy/unreachable_functions/grader/reference_output.jsonl"
    )
    task = _make_task_from_grader_file(
        tmp_path / "task",
        grader_src,
        ref_src,
        instance_id="verification_heavy__unreachable_functions",
        category="verification_heavy",
        output_artifact="output/unreachable.jsonl",
    )

    scratch = tmp_path / "scratch"
    # Build a src/ tree where ALL functions are reachable from main().
    src_dir = scratch / "src"
    src_dir.mkdir(parents=True)
    (src_dir / "main.py").write_text(
        "from helpers import helper_a, helper_b\n\n"
        "def main():\n"
        "    helper_a()\n"
        "    helper_b()\n"
    )
    (src_dir / "helpers.py").write_text(
        "def helper_a():\n"
        "    pass\n\n"
        "def helper_b():\n"
        "    pass\n"
    )
    # Correct answer: no unreachable functions → empty output file.
    output_dir = scratch / "output"
    output_dir.mkdir()
    (output_dir / "unreachable.jsonl").write_text("")

    result = invoke_grader(task, scratch)
    assert result.passed is True, f"expected PASS but got: {result.detail}"
    assert result.score == 1.0


def test_unreachable_functions_empty_output_fail_when_reference_nonempty(tmp_path: Path) -> None:
    """Issue #185 guard: when the real src/ has unreachable functions, empty output must FAIL."""
    import shutil

    grader_src = (
        _REPO_ROOT
        / "problems/artifact/verification_heavy/unreachable_functions/grader/hidden.py"
    )
    ref_src = (
        _REPO_ROOT
        / "problems/artifact/verification_heavy/unreachable_functions/grader/reference_output.jsonl"
    )
    task = _make_task_from_grader_file(
        tmp_path / "task",
        grader_src,
        ref_src,
        instance_id="verification_heavy__unreachable_functions",
        category="verification_heavy",
        output_artifact="output/unreachable.jsonl",
    )

    scratch = tmp_path / "scratch"
    # Use the real workspace src/ — has several unreachable functions.
    real_src = (
        _REPO_ROOT
        / "problems/artifact/verification_heavy/unreachable_functions/workspace/src"
    )
    import shutil
    shutil.copytree(real_src, scratch / "src")
    output_dir = scratch / "output"
    output_dir.mkdir()
    (output_dir / "unreachable.jsonl").write_text("")

    result = invoke_grader(task, scratch)
    assert result.passed is False, f"expected FAIL but got: {result.detail}"
    assert "empty" in result.detail


def test_upgrade_impact_empty_output_pass(tmp_path: Path) -> None:
    """Issue #185: when the upgrade causes zero conflicts, empty output must PASS.

    Constructs a packages.json where all dependency constraints on the upgraded
    package are satisfied by the new version, so the conflict set is empty.
    An agent that correctly produces an empty output/conflicts.jsonl should
    receive passed=True, score=1.0 — not the old false-negative FAIL.
    """
    import json

    grader_src = (
        _REPO_ROOT
        / "problems/artifact/verification_heavy/upgrade_impact/grader/hidden.py"
    )
    ref_src = (
        _REPO_ROOT
        / "problems/artifact/verification_heavy/upgrade_impact/grader/reference_output.jsonl"
    )
    task = _make_task_from_grader_file(
        tmp_path / "task",
        grader_src,
        ref_src,
        instance_id="verification_heavy__upgrade_impact",
        category="verification_heavy",
        output_artifact="output/conflicts.jsonl",
    )

    scratch = tmp_path / "scratch"
    scratch.mkdir()

    # Build a packages.json where upgrading "lib" to 2.0.0 satisfies ALL
    # constraints (>=1.0.0 and ^1.0.0 both accept 2.0.0 only via >=, but
    # we use >=1.0.0 and >=2.0.0 to guarantee zero conflicts).
    packages_data = {
        "packages": {
            "app-alpha": {
                "version": "1.0.0",
                "dependencies": {"lib": ">=1.0.0"},
            },
            "app-beta": {
                "version": "2.0.0",
                "dependencies": {"lib": ">=2.0.0"},
            },
        },
        "upgrade": {"package": "lib", "from": "1.5.0", "to": "2.0.0"},
    }
    (scratch / "packages.json").write_text(json.dumps(packages_data))
    # Correct answer: zero conflicts → empty output file.
    output_dir = scratch / "output"
    output_dir.mkdir()
    (output_dir / "conflicts.jsonl").write_text("")

    result = invoke_grader(task, scratch)
    assert result.passed is True, f"expected PASS but got: {result.detail}"
    assert result.score == 1.0


def test_upgrade_impact_empty_output_fail_when_reference_nonempty(tmp_path: Path) -> None:
    """Issue #185 guard: when there are real conflicts, empty output must FAIL."""
    import json

    grader_src = (
        _REPO_ROOT
        / "problems/artifact/verification_heavy/upgrade_impact/grader/hidden.py"
    )
    ref_src = (
        _REPO_ROOT
        / "problems/artifact/verification_heavy/upgrade_impact/grader/reference_output.jsonl"
    )
    task = _make_task_from_grader_file(
        tmp_path / "task",
        grader_src,
        ref_src,
        instance_id="verification_heavy__upgrade_impact",
        category="verification_heavy",
        output_artifact="output/conflicts.jsonl",
    )

    scratch = tmp_path / "scratch"
    scratch.mkdir()

    # Use the real packages.json — has 3 conflicts.
    import shutil
    shutil.copy(
        _REPO_ROOT
        / "problems/artifact/verification_heavy/upgrade_impact/workspace/packages.json",
        scratch / "packages.json",
    )
    output_dir = scratch / "output"
    output_dir.mkdir()
    (output_dir / "conflicts.jsonl").write_text("")

    result = invoke_grader(task, scratch)
    assert result.passed is False, f"expected FAIL but got: {result.detail}"
    assert "empty" in result.detail
