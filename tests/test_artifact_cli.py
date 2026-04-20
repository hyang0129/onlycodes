"""Tests for the ``python -m swebench artifact`` CLI wiring."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from swebench import artifact_run as artifact_run_mod
from swebench import artifact_cli as artifact_cli_mod
from swebench.cli import cli


def _write_fixture_task(tasks_root: Path, agent_answer: str = "42") -> str:
    """Create a minimal valid task at tasks/test_fixture/trivial_pass/. Returns instance_id."""
    task_dir = tasks_root / "test_fixture" / "trivial_pass"
    (task_dir / "workspace").mkdir(parents=True, exist_ok=True)
    (task_dir / "grader").mkdir(parents=True, exist_ok=True)
    (task_dir / "prompt.md").write_text("write 42 to answer.txt\n")
    (task_dir / "grader" / "hidden.py").write_text(textwrap.dedent("""
        class R:
            passed = False
            score = 0.0
            detail = ""

        def grade(scratch_dir):
            r = R()
            a = scratch_dir / "answer.txt"
            if not a.exists():
                r.detail = "missing"
                return r
            r.passed = a.read_text().strip() == "42"
            r.score = 1.0 if r.passed else 0.0
            r.detail = "ok" if r.passed else "mismatch"
            return r
    """))
    (task_dir / "grader" / "reference_output.txt").write_text("42\n")

    with open(task_dir / "task.yaml", "w") as f:
        yaml.safe_dump({
            "instance_id": "test_fixture__trivial_pass",
            "category": "test_fixture",
            "difficulty": "easy",
            "problem_statement": "prompt.md",
            "workspace_dir": "workspace/",
            "output_artifact": "answer.txt",
            "hidden_grader": "grader/hidden.py",
            "reference_output": "grader/reference_output.txt",
            "execution_budget": {"max_code_runs": 0, "max_wall_seconds": 0},
        }, f, sort_keys=False)
    return "test_fixture__trivial_pass"


@pytest.fixture
def stub_runtime(monkeypatch):
    """Stub out Claude launch and binary discovery so CLI tests stay hermetic."""
    monkeypatch.setattr(
        artifact_cli_mod, "find_claude_binary",
        lambda: "/bin/true",
    )
    monkeypatch.setattr(
        artifact_run_mod, "get_claude_version",
        lambda _b: "claude-test",
    )

    def fake_run_claude(*, prompt, repo_dir, system_prompt, tools_flags,
                        result_file, claude_binary):
        Path(repo_dir, "answer.txt").write_text("42\n")
        with open(result_file, "a") as f:
            f.write('{"type":"result","total_cost_usd":0.01,"num_turns":2}\n')

    monkeypatch.setattr(artifact_run_mod, "run_claude", fake_run_claude)
    return monkeypatch


def test_artifact_run_help():
    runner = CliRunner()
    r = runner.invoke(cli, ["artifact", "run", "--help"])
    assert r.exit_code == 0
    assert "--filter" in r.output
    assert "--arms" in r.output
    assert "--runs" in r.output


def test_artifact_verify_is_placeholder():
    runner = CliRunner()
    r = runner.invoke(cli, ["artifact", "verify"])
    # Placeholder exits 2 with a pointer message.
    assert r.exit_code == 2
    assert "placeholder" in (r.output + r.stderr).lower()


def test_artifact_run_end_to_end(tmp_path, stub_runtime):
    tasks_root = tmp_path / "tasks"
    results_dir = tmp_path / "results"
    iid = _write_fixture_task(tasks_root)

    runner = CliRunner()
    r = runner.invoke(cli, [
        "artifact", "run",
        "--tasks-dir", str(tasks_root),
        "--output-dir", str(results_dir),
        "--filter", iid,
        "--arms", "both",
    ])
    assert r.exit_code == 0, r.output

    for arm in ("code_only", "tool_rich"):
        run_dir = results_dir / iid / arm / "run1"
        assert (run_dir / "result.json").is_file()
        assert (run_dir / "agent.jsonl").is_file()
        scratch = run_dir / "scratch"
        assert (scratch / "answer.txt").read_text() == "42\n"
        # No-leak invariant — this is the falsifiability check.
        assert not any(scratch.rglob("hidden.py"))
        assert not any(scratch.rglob("reference_output*"))
        data = json.loads((run_dir / "result.json").read_text())
        assert data["verdict"] == "PASS"
        assert data["arm"] == arm


def test_artifact_run_single_arm(tmp_path, stub_runtime):
    tasks_root = tmp_path / "tasks"
    results_dir = tmp_path / "results"
    iid = _write_fixture_task(tasks_root)
    runner = CliRunner()
    r = runner.invoke(cli, [
        "artifact", "run",
        "--tasks-dir", str(tasks_root),
        "--output-dir", str(results_dir),
        "--filter", iid,
        "--arms", "code_only",
    ])
    assert r.exit_code == 0, r.output
    assert (results_dir / iid / "code_only" / "run1" / "result.json").is_file()
    assert not (results_dir / iid / "tool_rich").exists()


def test_artifact_run_resume_skips(tmp_path, stub_runtime):
    tasks_root = tmp_path / "tasks"
    results_dir = tmp_path / "results"
    iid = _write_fixture_task(tasks_root)
    runner = CliRunner()
    # First run
    r1 = runner.invoke(cli, [
        "artifact", "run",
        "--tasks-dir", str(tasks_root),
        "--output-dir", str(results_dir),
        "--filter", iid,
        "--arms", "code_only",
    ])
    assert r1.exit_code == 0
    # Second run with --resume (default on) must skip.
    r2 = runner.invoke(cli, [
        "artifact", "run",
        "--tasks-dir", str(tasks_root),
        "--output-dir", str(results_dir),
        "--filter", iid,
        "--arms", "code_only",
    ])
    assert r2.exit_code == 0
    assert "Skipping" in r2.output


def test_artifact_run_filter_no_match(tmp_path, stub_runtime):
    tasks_root = tmp_path / "tasks"
    _write_fixture_task(tasks_root)
    runner = CliRunner()
    r = runner.invoke(cli, [
        "artifact", "run",
        "--tasks-dir", str(tasks_root),
        "--output-dir", str(tmp_path / "results"),
        "--filter", "does_not_exist__nope",
    ])
    assert r.exit_code == 1
    assert "No matching" in (r.output + r.stderr)


def test_artifact_run_no_tasks(tmp_path, stub_runtime):
    tasks_root = tmp_path / "tasks"
    tasks_root.mkdir()
    runner = CliRunner()
    r = runner.invoke(cli, [
        "artifact", "run",
        "--tasks-dir", str(tasks_root),
        "--output-dir", str(tmp_path / "results"),
    ])
    assert r.exit_code == 1
    assert "No tasks found" in (r.output + r.stderr)


def test_default_output_dir_is_outside_repo(monkeypatch):
    """Issue #108: default --output-dir must NOT live under the onlycodes repo.

    The agent's Python kernel runs with cwd=scratch_dir; if scratch_dir were
    under the repo, the agent could traverse to tasks/<cat>/<slug>/grader/.
    This test pins the default to an absolute path outside the repo tree.
    """
    import os
    from swebench import artifact_cli as mod
    from swebench import repo_root

    default = Path(mod.DEFAULT_RESULTS_ROOT).resolve()
    repo = repo_root().resolve()
    # The default must not be inside the repo tree. commonpath is a safe check.
    common = os.path.commonpath([str(default), str(repo)])
    assert common != str(repo), (
        f"DEFAULT_RESULTS_ROOT {default} is inside repo {repo}; "
        "an agent rooted here can reach tasks/<cat>/<slug>/grader/."
    )
    # And the documented default is /tmp/onlycodes-artifact (path convention).
    assert str(default).startswith("/tmp/"), default


def test_result_json_records_leak_detected_field(tmp_path, stub_runtime):
    """Every result.json written by ``artifact run`` must carry leak_detected."""
    tasks_root = tmp_path / "tasks"
    results_dir = tmp_path / "results"
    iid = _write_fixture_task(tasks_root)
    runner = CliRunner()
    r = runner.invoke(cli, [
        "artifact", "run",
        "--tasks-dir", str(tasks_root),
        "--output-dir", str(results_dir),
        "--filter", iid,
        "--arms", "code_only",
    ])
    assert r.exit_code == 0, r.output
    data = json.loads(
        (results_dir / iid / "code_only" / "run1" / "result.json").read_text()
    )
    assert "leak_detected" in data
    # The fixture grader has no sentinel and a very short reference file, so
    # the audit yields no fingerprints -> leak_detected stays False.
    assert data["leak_detected"] is False


def test_swebench_run_unchanged_smoke():
    """Additive-only: ``python -m swebench run --help`` must still work and
    must not advertise any artifact-mode flag."""
    runner = CliRunner()
    r = runner.invoke(cli, ["run", "--help"])
    assert r.exit_code == 0
    assert "--filter" in r.output
    # The artifact arm names must not leak into the SWE-bench run help.
    assert "code_only" not in r.output
    assert "tool_rich" not in r.output
