"""Tests for swebench.artifact_run — end-to-end arm execution with a stubbed Claude.

We monkeypatch ``swebench.harness.run_claude`` so no real Claude binary is
invoked. The agent behaviour is simulated by writing output files into the
scratch dir directly.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from swebench import artifact_run as artifact_run_mod
from swebench.artifact_models import ExecutionBudget, Task
from swebench.artifact_run import (
    ARMS,
    _build_prompt,
    _build_tools_flags,
    is_run_complete,
    run_artifact_arm,
    run_dir_for,
)


def _make_fixture(task_dir: Path, grader_src: str, budget=(0, 0)) -> Task:
    (task_dir / "workspace").mkdir(parents=True, exist_ok=True)
    (task_dir / "workspace" / "starter.txt").write_text("START\n")
    (task_dir / "grader").mkdir(parents=True, exist_ok=True)
    (task_dir / "grader" / "hidden.py").write_text(textwrap.dedent(grader_src))
    (task_dir / "grader" / "reference_output.txt").write_text("42\n")
    (task_dir / "prompt.md").write_text("write 42 to answer.txt\n")
    return Task(
        instance_id="test_fixture__trivial_pass",
        category="test_fixture",
        difficulty="easy",
        problem_statement="prompt.md",
        workspace_dir="workspace/",
        output_artifact="answer.txt",
        hidden_grader="grader/hidden.py",
        reference_output="grader/reference_output.txt",
        execution_budget=ExecutionBudget(*budget),
        task_dir=task_dir.resolve(),
    )


_GRADER_CHECKS_42 = """
    class R:
        passed = False
        score = 0.0
        detail = ""

    def grade(scratch_dir):
        r = R()
        artifact = scratch_dir / "answer.txt"
        if not artifact.exists():
            r.detail = "output artifact not produced"
            return r
        val = artifact.read_text().strip()
        r.passed = val == "42"
        r.score = 1.0 if r.passed else 0.0
        r.detail = "ok" if r.passed else f"got {val!r}"
        return r
"""


def _stub_claude_writes(contents: str):
    """Return a fake run_claude that drops a file named answer.txt in cwd."""
    def fake_run_claude(*, prompt, repo_dir, system_prompt, tools_flags,
                       result_file, claude_binary):
        # Simulate the agent writing its artifact into the scratch dir.
        Path(repo_dir, "answer.txt").write_text(contents)
        # Also append a fake stream-json entry so cost/turns extraction paths run.
        with open(result_file, "a") as f:
            f.write(json.dumps({
                "type": "result",
                "total_cost_usd": 0.0123,
                "num_turns": 4,
            }) + "\n")
    return fake_run_claude


@pytest.fixture
def stub_claude(monkeypatch):
    """Replace run_claude + get_claude_version with harmless stubs."""
    monkeypatch.setattr(
        artifact_run_mod, "get_claude_version",
        lambda _b: "claude-test-1.0.0",
    )
    return monkeypatch


def test_build_tools_flags_code_only_includes_blocked_builtins():
    flags = _build_tools_flags("code_only", mcp_config_path="/tmp/mcp.json")
    assert "--mcp-config" in flags
    assert "--strict-mcp-config" in flags
    assert "--disallowedTools" in flags
    # Matched verbatim with run.py — confirm a few canary tools.
    disallowed = flags[flags.index("--disallowedTools") + 1]
    for name in ("Bash", "Read", "Write", "Edit", "Grep"):
        assert name in disallowed


def test_build_tools_flags_tool_rich_empty():
    assert _build_tools_flags("tool_rich", mcp_config_path="/tmp/mcp.json") == []


def test_build_tools_flags_rejects_unknown_arm():
    with pytest.raises(ValueError):
        _build_tools_flags("nonsense", mcp_config_path=None)


def test_run_artifact_arm_end_to_end_pass(tmp_path, stub_claude, monkeypatch):
    task = _make_fixture(tmp_path / "task", _GRADER_CHECKS_42)
    monkeypatch.setattr(
        artifact_run_mod, "run_claude",
        _stub_claude_writes("42\n"),
    )
    results_dir = tmp_path / "results"
    result = run_artifact_arm(
        task, "code_only", 1,
        results_dir=results_dir,
        claude_binary="/bin/true",
        echo=lambda _m: None,
    )
    assert result.verdict == "PASS"
    assert result.grade_result is not None
    assert result.grade_result.passed is True
    assert result.grade_result.score == 1.0
    assert result.budget == {
        "max_code_runs": 0, "max_wall_seconds": 0, "enforcement": "OFF",
    }
    # Cost / turns parsed from stubbed stream-json.
    assert result.cost_usd == pytest.approx(0.0123)
    assert result.num_turns == 4

    run_dir = run_dir_for(results_dir, task.instance_id, "code_only", 1)
    assert (run_dir / "result.json").is_file()
    assert (run_dir / "agent.jsonl").is_file()
    assert (run_dir / "scratch" / "answer.txt").read_text() == "42\n"
    # Starter workspace file must have been copied.
    assert (run_dir / "scratch" / "starter.txt").read_text() == "START\n"


def test_run_artifact_arm_fail_verdict(tmp_path, stub_claude, monkeypatch):
    task = _make_fixture(tmp_path / "task", _GRADER_CHECKS_42)
    monkeypatch.setattr(
        artifact_run_mod, "run_claude",
        _stub_claude_writes("wrong\n"),
    )
    results_dir = tmp_path / "results"
    result = run_artifact_arm(
        task, "tool_rich", 1,
        results_dir=results_dir,
        claude_binary="/bin/true",
        echo=lambda _m: None,
    )
    assert result.verdict == "FAIL"
    assert result.grade_result is not None
    assert result.grade_result.passed is False


def test_run_artifact_arm_no_leak_in_scratch(tmp_path, stub_claude, monkeypatch):
    task = _make_fixture(tmp_path / "task", _GRADER_CHECKS_42)
    monkeypatch.setattr(
        artifact_run_mod, "run_claude",
        _stub_claude_writes("42\n"),
    )
    results_dir = tmp_path / "results"
    run_artifact_arm(
        task, "code_only", 1,
        results_dir=results_dir,
        claude_binary="/bin/true",
        echo=lambda _m: None,
    )
    scratch = results_dir / task.instance_id / "code_only" / "run1" / "scratch"
    # ABSOLUTE invariant: no grader/hidden.py, no reference_output.* in scratch.
    assert not any(scratch.rglob("hidden.py"))
    assert not any(scratch.rglob("reference_output*"))


def test_budget_log_unlimited(tmp_path, stub_claude, monkeypatch, capsys):
    task = _make_fixture(tmp_path / "task", _GRADER_CHECKS_42, budget=(0, 0))
    monkeypatch.setattr(
        artifact_run_mod, "run_claude",
        _stub_claude_writes("42\n"),
    )
    captured: list[str] = []
    run_artifact_arm(
        task, "code_only", 1,
        results_dir=tmp_path / "results",
        claude_binary="/bin/true",
        echo=captured.append,
    )
    joined = "\n".join(captured)
    assert "budget enforcement OFF (0 = unlimited)" in joined


def test_budget_log_nonzero(tmp_path, stub_claude, monkeypatch):
    task = _make_fixture(tmp_path / "task", _GRADER_CHECKS_42, budget=(10, 300))
    monkeypatch.setattr(
        artifact_run_mod, "run_claude",
        _stub_claude_writes("42\n"),
    )
    captured: list[str] = []
    result = run_artifact_arm(
        task, "code_only", 1,
        results_dir=tmp_path / "results",
        claude_binary="/bin/true",
        echo=captured.append,
    )
    joined = "\n".join(captured)
    assert "max_code_runs=10" in joined
    assert "max_wall_seconds=300" in joined
    assert "enforcement OFF" in joined
    # Fields are stored on the result even though enforcement is off.
    assert result.budget == {
        "max_code_runs": 10, "max_wall_seconds": 300, "enforcement": "OFF",
    }


def test_is_run_complete_true_false(tmp_path):
    run_dir = tmp_path / "r"
    run_dir.mkdir()
    assert not is_run_complete(run_dir)
    (run_dir / "result.json").write_text(json.dumps({"verdict": "PASS"}))
    assert is_run_complete(run_dir)
    (run_dir / "result.json").write_text(json.dumps({"verdict": "ERROR"}))
    assert not is_run_complete(run_dir)


def test_arm_list_constants():
    assert set(ARMS) == {"code_only", "tool_rich"}


def test_build_prompt_uses_absolute_paths(tmp_path):
    """Regression for #107: agent must receive absolute paths, not relative.

    The MCP ``execute_code`` tool defaults to a fresh tmpdir when the agent
    omits ``cwd=`` on a call. Relative paths in the prompt would resolve
    against that tmpdir, not scratch_dir — so the output artifact would land
    outside where the grader looks. Absolute paths remove the ambiguity.
    """
    task_dir = tmp_path / "task"
    task = _make_fixture(task_dir, _GRADER_CHECKS_42)
    scratch = tmp_path / "results" / task.instance_id / "code_only" / "run1" / "scratch"
    scratch.mkdir(parents=True)

    prompt = _build_prompt(task, scratch, "code_only")

    scratch_abs = str(scratch.resolve())
    output_abs = str((scratch.resolve() / task.output_artifact))

    # Must contain absolute scratch path and absolute output path.
    assert scratch_abs in prompt
    assert output_abs in prompt
    # Must NOT contain the old "relative path" framing that caused #107.
    assert "relative path" not in prompt
