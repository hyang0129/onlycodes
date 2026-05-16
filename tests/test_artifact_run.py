"""Tests for swebench.artifact_run — end-to-end arm execution with a stubbed runner.

We inject a FakeRunner so no real agent binary is invoked. The agent behaviour
is simulated by writing output files into the scratch dir directly.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from swebench.artifact_models import ExecutionBudget, Task
from swebench.artifact_run import (
    ARMS,
    _build_prompt,
    is_run_complete,
    run_artifact_arm,
    run_dir_for,
)
from swebench.runner import AgentRunner, ClaudeRunner, BLOCKED_BUILTINS


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


class FakeRunner(AgentRunner):
    """Test double for AgentRunner. Writes a fixed artifact and fake JSONL."""

    surface = "claude_code"

    def __init__(self, artifact_content: str = "42\n"):
        self._artifact_content = artifact_content

    def find_binary(self) -> str:
        return "/bin/true"

    def verify_auth(self) -> None:
        return

    def get_version(self, binary: str) -> str:
        return "fake-runner-1.0.0"

    def build_tools_flags(self, arm: str, mcp_config_path) -> list[str]:
        return ClaudeRunner().build_tools_flags(arm, mcp_config_path)

    def invoke(self, *, prompt, cwd, system_prompt, tools_flags,
               result_file, binary, mcp_config_path=None,
               wall_timeout_seconds: int = 3600) -> None:
        Path(cwd, "answer.txt").write_text(self._artifact_content)
        with open(result_file, "a") as f:
            f.write(json.dumps({
                "type": "result",
                "total_cost_usd": 0.0123,
                "num_turns": 4,
            }) + "\n")

    def extract_metadata(self, jsonl_path):
        return ClaudeRunner().extract_metadata(jsonl_path)


# ---------------------------------------------------------------------------
# ClaudeRunner.build_tools_flags tests (replaces old _build_tools_flags tests)
# ---------------------------------------------------------------------------

def test_build_tools_flags_code_only_includes_blocked_builtins():
    flags = ClaudeRunner().build_tools_flags("code_only", mcp_config_path="/tmp/mcp.json")
    assert "--mcp-config" in flags
    assert "--strict-mcp-config" in flags
    assert "--disallowedTools" in flags
    disallowed = flags[flags.index("--disallowedTools") + 1]
    for name in ("Bash", "Read", "Write", "Edit", "Grep"):
        assert name in disallowed


def test_build_tools_flags_tool_rich_empty():
    assert ClaudeRunner().build_tools_flags("tool_rich", mcp_config_path="/tmp/mcp.json") == []


def test_build_tools_flags_rejects_unknown_arm():
    with pytest.raises(ValueError):
        ClaudeRunner().build_tools_flags("nonsense", mcp_config_path=None)


def test_build_tools_flags_bash_only():
    flags = ClaudeRunner().build_tools_flags("bash_only", mcp_config_path=None)
    assert "--tools" in flags
    assert flags[flags.index("--tools") + 1] == "Bash"
    assert "--disallowedTools" in flags
    disallowed = flags[flags.index("--disallowedTools") + 1]
    assert "Bash" not in disallowed
    assert "Read" in disallowed
    assert "--mcp-config" not in flags
    assert "--strict-mcp-config" not in flags


# ---------------------------------------------------------------------------
# BLOCKED_BUILTINS canonical source
# ---------------------------------------------------------------------------

def test_blocked_builtins_contains_expected_tools():
    for name in ("Bash", "Read", "Write", "Edit", "Grep", "WebSearch"):
        assert name in BLOCKED_BUILTINS


# ---------------------------------------------------------------------------
# run_artifact_arm end-to-end tests
# ---------------------------------------------------------------------------

def test_run_artifact_arm_end_to_end_pass(tmp_path):
    task = _make_fixture(tmp_path / "task", _GRADER_CHECKS_42)
    results_dir = tmp_path / "results"
    result = run_artifact_arm(
        task, "code_only", 1,
        results_dir=results_dir,
        runner=FakeRunner("42\n"),
        echo=lambda _m: None,
    )
    assert result.verdict == "PASS"
    assert result.grade_result is not None
    assert result.grade_result.passed is True
    assert result.grade_result.score == 1.0
    assert result.agent_surface == "claude_code"
    assert result.agent_version == "fake-runner-1.0.0"
    assert result.budget == {
        "max_code_runs": 0, "max_wall_seconds": 0, "enforcement": "OFF",
    }
    assert result.cost_usd == pytest.approx(0.0123)
    assert result.num_turns == 4

    run_dir = run_dir_for(results_dir, task.instance_id, "code_only", 1)
    assert (run_dir / "result.json").is_file()
    assert (run_dir / "agent.jsonl").is_file()
    assert (run_dir / "scratch" / "answer.txt").read_text() == "42\n"
    assert (run_dir / "scratch" / "starter.txt").read_text() == "START\n"

    # result.json must include agent_surface
    data = json.loads((run_dir / "result.json").read_text())
    assert data["agent_surface"] == "claude_code"


def test_run_artifact_arm_fail_verdict(tmp_path):
    task = _make_fixture(tmp_path / "task", _GRADER_CHECKS_42)
    result = run_artifact_arm(
        task, "tool_rich", 1,
        results_dir=tmp_path / "results",
        runner=FakeRunner("wrong\n"),
        echo=lambda _m: None,
    )
    assert result.verdict == "FAIL"
    assert result.grade_result is not None
    assert result.grade_result.passed is False


def test_run_artifact_arm_no_leak_in_scratch(tmp_path):
    task = _make_fixture(tmp_path / "task", _GRADER_CHECKS_42)
    run_artifact_arm(
        task, "code_only", 1,
        results_dir=tmp_path / "results",
        runner=FakeRunner("42\n"),
        echo=lambda _m: None,
    )
    scratch = tmp_path / "results" / task.instance_id / "code_only" / "run1" / "scratch"
    assert not any(scratch.rglob("hidden.py"))
    assert not any(scratch.rglob("reference_output*"))


def test_budget_log_unlimited(tmp_path):
    task = _make_fixture(tmp_path / "task", _GRADER_CHECKS_42, budget=(0, 0))
    captured: list[str] = []
    run_artifact_arm(
        task, "code_only", 1,
        results_dir=tmp_path / "results",
        runner=FakeRunner("42\n"),
        echo=captured.append,
    )
    assert "budget enforcement OFF (0 = unlimited)" in "\n".join(captured)


def test_budget_log_nonzero(tmp_path):
    task = _make_fixture(tmp_path / "task", _GRADER_CHECKS_42, budget=(10, 300))
    captured: list[str] = []
    result = run_artifact_arm(
        task, "code_only", 1,
        results_dir=tmp_path / "results",
        runner=FakeRunner("42\n"),
        echo=captured.append,
    )
    joined = "\n".join(captured)
    assert "max_code_runs=10" in joined
    assert "max_wall_seconds=300" in joined
    assert "enforcement OFF" in joined
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
    assert set(ARMS) == {"code_only", "tool_rich", "bash_only"}


def test_run_artifact_arm_end_to_end_bash_only(tmp_path):
    task = _make_fixture(tmp_path / "task", _GRADER_CHECKS_42)
    result = run_artifact_arm(
        task, "bash_only", 1,
        results_dir=tmp_path / "results",
        runner=FakeRunner("42\n"),
        echo=lambda _m: None,
    )
    assert result.arm == "bash_only"
    assert result.verdict == "PASS"
    assert result.grade_result is not None
    assert result.grade_result.passed is True


def test_build_prompt_uses_absolute_paths(tmp_path):
    """Regression for #107: agent must receive absolute paths, not relative."""
    task_dir = tmp_path / "task"
    task = _make_fixture(task_dir, _GRADER_CHECKS_42)
    scratch = tmp_path / "results" / task.instance_id / "code_only" / "run1" / "scratch"
    scratch.mkdir(parents=True)

    prompt = _build_prompt(task, scratch, "code_only")

    scratch_abs = str(scratch.resolve())
    output_abs = str((scratch.resolve() / task.output_artifact))

    assert scratch_abs in prompt
    assert output_abs in prompt
    assert "relative path" not in prompt
