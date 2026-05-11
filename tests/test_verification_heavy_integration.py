"""Integration tests: full artifact-run pipeline for verification_heavy tasks.

# SCENARIO: slice-verification-heavy-full-run
# layers_involved: swebench/artifact_cli.py, swebench/artifact_loader.py,
#   swebench/artifact_materialize.py, swebench/artifact_grade.py,
#   swebench/artifact_run.py,
#   problems/artifact/verification_heavy/unreachable_functions/grader/hidden.py,
#   problems/artifact/verification_heavy/upgrade_impact/grader/hidden.py

These tests exercise the full vertical slice from the ``artifact run`` CLI entry
point through to the written result.json, using the real verification_heavy
task manifests added in issue #185.

They are wiring-tier tests: assertions target structure and status codes, not
exact artifact content.

Key integration boundaries validated here that are NOT covered by unit or
component tests:

1. CLI → loader → materialize → grader subprocess → result.json (schema, verdict).
2. The ``_all_output`` click-version compat helper applies in CLI error paths
   (filter-no-match, no-tasks) so the messages survive click 8.1→8.3+ upgrades.
3. The no-leak invariant holds for real verification_heavy tasks (grader/hidden.py
   and reference_output.* must not appear in scratch dir).
4. A correct empty-output agent answer produces PASS (the bug fixed in #185).

Infrastructure requirement: Python + pip + the project .venv only. No network,
no docker, no database.  Tests that require the real workspace src/ (for the
grader to analyse) are always available; no skip guard needed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swebench import artifact_cli as artifact_cli_mod
from swebench import artifact_run as artifact_run_mod
from swebench.cli import cli

try:
    from click.testing import CliRunner
except ImportError:
    pytest.skip("click not installed", allow_module_level=True)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PROBLEMS_DIR = _REPO_ROOT / "problems" / "artifact"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _all_output(r) -> str:
    """Concatenate stdout and stderr from a click Result, version-agnostic.

    click 8.1 mixes stderr into stdout by default; click 8.2+ separates them.
    This helper works with both.
    """
    try:
        extra = r.stderr or ""
    except (ValueError, AttributeError):
        return r.output
    return r.output + extra


@pytest.fixture
def stub_runtime_unreachable(monkeypatch, tmp_path):
    """Stub Claude so it writes the correct answer for unreachable_functions.

    The correct output is a JSONL file listing the seven unreachable functions
    from the committed workspace src/ tree.
    """
    monkeypatch.setattr(artifact_cli_mod, "find_claude_binary", lambda: "/bin/true")
    monkeypatch.setattr(
        artifact_run_mod, "get_claude_version", lambda _b: "claude-stub-1.0.0"
    )

    correct_lines = [
        '{"function": "_log_cancellation", "module": "services"}',
        '{"function": "build_sms_body", "module": "notifications"}',
        '{"function": "cancel_order", "module": "services"}',
        '{"function": "compute_discount", "module": "utils"}',
        '{"function": "format_address", "module": "notifications"}',
        '{"function": "refund_payment", "module": "services"}',
        '{"function": "sanitize_input", "module": "utils"}',
    ]

    def fake_run_claude(*, prompt, repo_dir, system_prompt, tools_flags,
                        result_file, claude_binary):
        scratch = Path(repo_dir)
        (scratch / "output").mkdir(parents=True, exist_ok=True)
        (scratch / "output" / "unreachable.jsonl").write_text(
            "\n".join(correct_lines) + "\n"
        )
        with open(result_file, "a") as f:
            f.write('{"type":"result","total_cost_usd":0.01,"num_turns":3}\n')

    monkeypatch.setattr(artifact_run_mod, "run_claude", fake_run_claude)
    return monkeypatch


@pytest.fixture
def stub_runtime_upgrade(monkeypatch, tmp_path):
    """Stub Claude so it writes the correct answer for upgrade_impact.

    The correct output is a JSONL file listing the three packages whose
    constraints conflict with the upgrade in the committed workspace packages.json.
    """
    monkeypatch.setattr(artifact_cli_mod, "find_claude_binary", lambda: "/bin/true")
    monkeypatch.setattr(
        artifact_run_mod, "get_claude_version", lambda _b: "claude-stub-1.0.0"
    )

    correct_lines = [
        '{"package": "api-gateway", "constraint": "~1.4.0"}',
        '{"package": "auth-service", "constraint": "1.4.2"}',
        '{"package": "web-server", "constraint": "^1.0.0"}',
    ]

    def fake_run_claude(*, prompt, repo_dir, system_prompt, tools_flags,
                        result_file, claude_binary):
        scratch = Path(repo_dir)
        (scratch / "output").mkdir(parents=True, exist_ok=True)
        (scratch / "output" / "conflicts.jsonl").write_text(
            "\n".join(correct_lines) + "\n"
        )
        with open(result_file, "a") as f:
            f.write('{"type":"result","total_cost_usd":0.01,"num_turns":3}\n')

    monkeypatch.setattr(artifact_run_mod, "run_claude", fake_run_claude)
    return monkeypatch


# ---------------------------------------------------------------------------
# Wiring tier — slice-verification-heavy-full-run
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not (_PROBLEMS_DIR / "verification_heavy").is_dir(),
    reason="problems/artifact/verification_heavy/ not present in this checkout",
)
def test_unreachable_functions_run_produces_pass_verdict(
    tmp_path, stub_runtime_unreachable
):
    """Full slice: CLI → loader → materialize → grader subprocess → result.json.

    Wiring assertions: the result.json exists, has the expected schema fields,
    and verdict is PASS when a correct answer is supplied. No exact golden
    comparison of cost/turns (volatile).
    """
    results_dir = tmp_path / "results"
    runner = CliRunner()

    r = runner.invoke(cli, [
        "artifact", "run",
        "--tasks-dir", str(_PROBLEMS_DIR),
        "--output-dir", str(results_dir),
        "--filter", "verification_heavy__unreachable_functions",
        "--arms", "tool_rich",
        "--runs", "1",
    ])

    assert r.exit_code == 0, f"CLI exited non-zero.\nOutput: {_all_output(r)}"

    # Structural assertions — wiring tier only
    run_dir = (
        results_dir
        / "verification_heavy__unreachable_functions"
        / "tool_rich"
        / "run1"
    )
    assert run_dir.is_dir(), f"Expected run dir {run_dir} to exist"
    result_path = run_dir / "result.json"
    assert result_path.is_file(), "result.json not written"
    agent_path = run_dir / "agent.jsonl"
    assert agent_path.is_file(), "agent.jsonl not written"

    data = json.loads(result_path.read_text())
    # Schema fields must be present (wiring: structure check)
    assert "verdict" in data, f"result.json missing 'verdict': {data}"
    assert "arm" in data, f"result.json missing 'arm': {data}"
    assert "instance_id" in data, f"result.json missing 'instance_id': {data}"
    assert "grade_result" in data, f"result.json missing 'grade_result': {data}"
    assert data["grade_result"] is not None, "grade_result must not be null on PASS"
    assert "score" in data["grade_result"], (
        f"grade_result missing 'score': {data['grade_result']}"
    )

    # Content assertions
    assert data["verdict"] == "PASS", (
        f"expected PASS but got {data['verdict']!r}; "
        f"detail: {data['grade_result'].get('detail', '') if data.get('grade_result') else ''}"
    )
    assert data["arm"] == "tool_rich"
    assert data["instance_id"] == "verification_heavy__unreachable_functions"
    assert data["grade_result"]["score"] == 1.0

    # No-leak invariant
    scratch = run_dir / "scratch"
    assert not any(scratch.rglob("hidden.py")), "grader hidden.py leaked into scratch"
    assert not any(scratch.rglob("reference_output*")), (
        "reference_output leaked into scratch"
    )


@pytest.mark.skipif(
    not (_PROBLEMS_DIR / "verification_heavy").is_dir(),
    reason="problems/artifact/verification_heavy/ not present in this checkout",
)
def test_upgrade_impact_run_produces_pass_verdict(tmp_path, stub_runtime_upgrade):
    """Full slice: CLI → loader → materialize → grader subprocess → result.json.

    Wiring assertions for upgrade_impact: result.json schema, PASS verdict,
    no-leak invariant.
    """
    results_dir = tmp_path / "results"
    runner = CliRunner()

    r = runner.invoke(cli, [
        "artifact", "run",
        "--tasks-dir", str(_PROBLEMS_DIR),
        "--output-dir", str(results_dir),
        "--filter", "verification_heavy__upgrade_impact",
        "--arms", "tool_rich",
        "--runs", "1",
    ])

    assert r.exit_code == 0, f"CLI exited non-zero.\nOutput: {_all_output(r)}"

    run_dir = (
        results_dir
        / "verification_heavy__upgrade_impact"
        / "tool_rich"
        / "run1"
    )
    assert run_dir.is_dir(), f"Expected run dir {run_dir} to exist"
    result_path = run_dir / "result.json"
    assert result_path.is_file(), "result.json not written"

    data = json.loads(result_path.read_text())
    assert "verdict" in data
    assert "arm" in data
    assert "instance_id" in data
    assert "grade_result" in data
    assert data["grade_result"] is not None, "grade_result must not be null on PASS"
    assert "score" in data["grade_result"]

    assert data["verdict"] == "PASS", (
        f"expected PASS; detail: {data['grade_result'].get('detail', '') if data.get('grade_result') else ''}"
    )
    assert data["arm"] == "tool_rich"
    assert data["instance_id"] == "verification_heavy__upgrade_impact"
    assert data["grade_result"]["score"] == 1.0

    scratch = run_dir / "scratch"
    assert not any(scratch.rglob("hidden.py")), "grader hidden.py leaked into scratch"
    assert not any(scratch.rglob("reference_output*")), (
        "reference_output leaked into scratch"
    )


@pytest.mark.skipif(
    not (_PROBLEMS_DIR / "verification_heavy").is_dir(),
    reason="problems/artifact/verification_heavy/ not present in this checkout",
)
def test_unreachable_functions_empty_output_produces_fail_verdict(
    tmp_path, monkeypatch
):
    """Integration guard: an agent that writes empty output for unreachable_functions
    when the workspace has real unreachable functions must produce FAIL.

    This verifies the grader's empty-output rejection path is wired through the
    full pipeline (not just isolated at the invoke_grader level).
    """
    monkeypatch.setattr(artifact_cli_mod, "find_claude_binary", lambda: "/bin/true")
    monkeypatch.setattr(
        artifact_run_mod, "get_claude_version", lambda _b: "claude-stub-1.0.0"
    )

    def fake_run_claude_empty(*, prompt, repo_dir, system_prompt, tools_flags,
                               result_file, claude_binary):
        scratch = Path(repo_dir)
        (scratch / "output").mkdir(parents=True, exist_ok=True)
        (scratch / "output" / "unreachable.jsonl").write_text("")
        with open(result_file, "a") as f:
            f.write('{"type":"result","total_cost_usd":0.01,"num_turns":1}\n')

    monkeypatch.setattr(artifact_run_mod, "run_claude", fake_run_claude_empty)

    results_dir = tmp_path / "results"
    runner = CliRunner()
    r = runner.invoke(cli, [
        "artifact", "run",
        "--tasks-dir", str(_PROBLEMS_DIR),
        "--output-dir", str(results_dir),
        "--filter", "verification_heavy__unreachable_functions",
        "--arms", "tool_rich",
        "--runs", "1",
    ])

    # CLI should still exit 0 (the task ran; grading returned FAIL)
    assert r.exit_code == 0, f"CLI crashed: {_all_output(r)}"

    run_dir = (
        results_dir
        / "verification_heavy__unreachable_functions"
        / "tool_rich"
        / "run1"
    )
    data = json.loads((run_dir / "result.json").read_text())
    assert data["verdict"] == "FAIL", (
        f"expected FAIL for empty output but got {data['verdict']!r}"
    )
    assert data["grade_result"] is not None
    assert data["grade_result"]["score"] == 0.0


@pytest.mark.skipif(
    not (_PROBLEMS_DIR / "verification_heavy").is_dir(),
    reason="problems/artifact/verification_heavy/ not present in this checkout",
)
def test_artifact_run_filter_no_match_returns_error_with_message(
    tmp_path, monkeypatch
):
    """CLI error path: --filter that matches no task must exit 1 with a
    message containing 'No matching'.

    This validates the _all_output compat helper: the message must be
    visible regardless of whether click routes it to stdout or stderr.
    """
    monkeypatch.setattr(artifact_cli_mod, "find_claude_binary", lambda: "/bin/true")

    runner = CliRunner()
    r = runner.invoke(cli, [
        "artifact", "run",
        "--tasks-dir", str(_PROBLEMS_DIR),
        "--output-dir", str(tmp_path / "results"),
        "--filter", "verification_heavy__does_not_exist_at_all",
    ])

    assert r.exit_code == 1
    assert "No matching" in _all_output(r), (
        f"Expected 'No matching' in output; got:\n{_all_output(r)}"
    )


def test_artifact_run_empty_tasks_dir_returns_error_with_message(
    tmp_path, monkeypatch
):
    """CLI error path: --tasks-dir pointing at an empty directory must exit 1
    with a message containing 'No tasks found'.

    Validates _all_output compat across click 8.1/8.2/8.3.
    """
    monkeypatch.setattr(artifact_cli_mod, "find_claude_binary", lambda: "/bin/true")

    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    runner = CliRunner()
    r = runner.invoke(cli, [
        "artifact", "run",
        "--tasks-dir", str(tasks_dir),
        "--output-dir", str(tmp_path / "results"),
    ])

    assert r.exit_code == 1
    assert "No tasks found" in _all_output(r), (
        f"Expected 'No tasks found' in output; got:\n{_all_output(r)}"
    )
