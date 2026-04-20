"""Tests for tools/verify_graders.py — reference_output sanity gate.

We run the tool as a subprocess so the exit-code contract is verified
end-to-end, mirroring how CI would invoke it.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_TOOL = Path(__file__).resolve().parent.parent / "tools" / "verify_graders.py"


def _run_tool(tasks_dir: Path) -> subprocess.CompletedProcess:
    env_patch = {"VERIFY_GRADERS_TASKS_DIR": str(tasks_dir)}
    import os
    env = os.environ.copy()
    env.update(env_patch)
    return subprocess.run(
        [sys.executable, str(_TOOL), "--tasks-dir", str(tasks_dir)],
        capture_output=True,
        text=True,
    )


def _make_task(task_dir: Path, grader_src: str, ref_content: str,
               workspace_content: str = "# empty\n") -> None:
    """Build a minimal artifact task under task_dir."""
    (task_dir / "workspace").mkdir(parents=True, exist_ok=True)
    (task_dir / "workspace" / "input.txt").write_text(workspace_content)
    (task_dir / "grader").mkdir(parents=True, exist_ok=True)
    (task_dir / "grader" / "hidden.py").write_text(textwrap.dedent(grader_src))
    (task_dir / "grader" / "reference_output.txt").write_text(ref_content)
    (task_dir / "prompt.md").write_text("produce answer.txt\n")
    (task_dir / "task.yaml").write_text(textwrap.dedent(f"""\
        instance_id: test_fixture__verify_{task_dir.name}
        category: test_fixture
        difficulty: easy
        problem_statement: prompt.md
        workspace_dir: workspace/
        output_artifact: answer.txt
        hidden_grader: grader/hidden.py
        reference_output: grader/reference_output.txt
        execution_budget:
          max_code_runs: 0
          max_wall_seconds: 0
    """))


_GRADER_CHECKS_42 = """
    class R:
        passed = False
        score = 0.0
        detail = ""

    def grade(scratch_dir):
        from pathlib import Path
        r = R()
        artifact = Path(scratch_dir) / "answer.txt"
        if not artifact.exists():
            r.detail = "output artifact not produced"
            return r
        val = artifact.read_text().strip()
        r.passed = val == "42"
        r.score = 1.0 if r.passed else 0.0
        r.detail = "ok" if r.passed else f"got {val!r}"
        return r
"""

_GRADER_ALWAYS_FAIL = """
    class R:
        passed = False
        score = 0.0
        detail = "always fails"

    def grade(scratch_dir):
        return R()
"""


def test_all_pass(tmp_path):
    tasks_dir = tmp_path / "tasks" / "test_fixture"
    task_dir = tasks_dir / "pass_task"
    _make_task(task_dir, _GRADER_CHECKS_42, "42\n")
    proc = _run_tool(tmp_path / "tasks")
    assert proc.returncode == 0
    assert "PASS" in proc.stdout
    assert "test_fixture__verify_pass_task" in proc.stdout


def test_fail_verdict(tmp_path):
    tasks_dir = tmp_path / "tasks" / "test_fixture"
    task_dir = tasks_dir / "fail_task"
    _make_task(task_dir, _GRADER_ALWAYS_FAIL, "42\n")
    proc = _run_tool(tmp_path / "tasks")
    assert proc.returncode == 1
    assert "FAIL" in proc.stdout


def test_missing_reference_output(tmp_path):
    tasks_dir = tmp_path / "tasks" / "test_fixture"
    task_dir = tasks_dir / "miss_task"
    _make_task(task_dir, _GRADER_CHECKS_42, "42\n")
    # Delete the reference_output file after creating the task.
    (task_dir / "grader" / "reference_output.txt").unlink()
    proc = _run_tool(tmp_path / "tasks")
    assert proc.returncode == 1
    assert "ERROR" in proc.stdout


def test_no_tasks_exits_2(tmp_path):
    empty_tasks = tmp_path / "tasks"
    empty_tasks.mkdir()
    proc = _run_tool(empty_tasks)
    assert proc.returncode == 2


def test_deterministic_output(tmp_path):
    tasks_dir = tmp_path / "tasks" / "test_fixture"
    task_dir = tasks_dir / "det_task"
    _make_task(task_dir, _GRADER_CHECKS_42, "42\n")
    proc1 = _run_tool(tmp_path / "tasks")
    proc2 = _run_tool(tmp_path / "tasks")
    assert proc1.stdout == proc2.stdout
    assert proc1.returncode == proc2.returncode
