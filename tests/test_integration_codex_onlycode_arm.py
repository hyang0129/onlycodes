"""Integration wiring tests for ``swebench run`` and ``swebench artifact run``
with ``codex_cli + onlycode / code_only`` arms — issue #251.

Scenario: slice-codex-run-onlycode-preflight
Scenario: slice-codex-artifact-code-only-preflight
Scenario: slice-codex-run-baseline-no-preflight
Tier: wiring

These tests exercise the full CLI dispatch path through Click
(swebench/cli.py → swebench/run.py / swebench/artifact_cli.py → swebench/runner.py)
without actually invoking codex or a real benchmark run.

What they verify (wiring only — no exact output comparison):
  1. ``swebench run --agent-surface codex_cli --arms onlycode`` no longer immediately
     exits 1 with "not yet implemented"; it now calls ``CodexRunner.preflight()``.
  2. ``swebench artifact run --agent-surface codex_cli --arms code_only`` no longer
     immediately exits 1 with "not yet implemented"; it calls ``CodexRunner.preflight()``.
  3. ``swebench run --agent-surface codex_cli --arms baseline`` does NOT call
     ``CodexRunner.preflight()`` (baseline arm does not need exec-server bundle).
  4. ``CODEX_NOT_IMPLEMENTED_MSG`` is no longer importable from ``swebench.runner``.
  5. The CLI response code and error message structure are schema-correct
     (non-zero exit when preflight fails, "Codex pre-flight failed" in output).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from swebench.cli import cli
from swebench.runner import CodexRunner


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner():
    return CliRunner()


def _make_monkeypatched_codex_env(monkeypatch, *, preflight_raises: bool = False):
    """Patch CodexRunner so it doesn't need a real binary or auth.json.

    Args:
        preflight_raises: if True, make preflight() raise RuntimeError
            (simulates missing exec-server bundle); if False, preflight is a no-op.
    """
    monkeypatch.setattr(
        "swebench.runner.CodexRunner.find_binary",
        lambda self: "/usr/bin/codex",
    )
    monkeypatch.setattr(
        "swebench.runner.CodexRunner.verify_auth",
        lambda self: None,
    )
    monkeypatch.setattr(
        "swebench.runner.CodexRunner.get_version",
        lambda self, _binary: "codex-test-1.0",
    )

    if preflight_raises:
        def _fail_preflight(self, mcp_config_path=None):
            raise RuntimeError("exec-server bundle not found (test-injected failure)")

        monkeypatch.setattr("swebench.runner.CodexRunner.preflight", _fail_preflight)
    else:
        monkeypatch.setattr(
            "swebench.runner.CodexRunner.preflight",
            lambda self, mcp_config_path=None: None,
        )


def _make_minimal_swe_problem(problems_dir: Path) -> None:
    """Create a minimal SWE-bench problem YAML so run_command gets past the problem-loading check."""
    problems_dir.mkdir(parents=True, exist_ok=True)
    yaml_content = (
        "instance_id: test__stub-1\n"
        "repo: test/stub\n"
        "base_commit: abc123\n"
        "test_cmd: echo ok\n"
        "problem_statement: stub problem\n"
        "patch_file: null\n"
        "added_at: '2026-01-01'\n"
        "hf_split: test\n"
    )
    (problems_dir / "stub.yaml").write_text(yaml_content)


# ---------------------------------------------------------------------------
# Scenario 1: slice-codex-run-onlycode-preflight
#
# swebench run --agent-surface codex_cli --arms onlycode must reach the
# CodexRunner.preflight() call, not exit immediately with "not yet implemented".
# ---------------------------------------------------------------------------


def test_codex_run_onlycode_calls_preflight_not_rejection(runner, monkeypatch, tmp_path):
    """codex_cli + onlycode arm must call preflight(), not emit a rejection error.

    Wiring assertion: the route from ``swebench run`` → ``run_command`` →
    ``CodexRunner.preflight()`` is connected. When preflight raises RuntimeError,
    the CLI must emit 'Codex pre-flight failed' (not 'not yet implemented').
    """
    _make_monkeypatched_codex_env(monkeypatch, preflight_raises=True)
    _make_minimal_swe_problem(tmp_path / "problems" / "swe")
    monkeypatch.setattr("swebench.run.repo_root", lambda: tmp_path)

    result = runner.invoke(
        cli,
        [
            "run",
            "--agent-surface", "codex_cli",
            "--arms", "onlycode",
            "--output-dir", str(tmp_path / "out"),
        ],
        catch_exceptions=False,
    )

    # Schema assertions: non-zero exit, correct error class in output.
    assert result.exit_code != 0, (
        f"Expected non-zero exit when preflight fails, got 0. Output:\n{result.output}"
    )
    combined = result.output or ""
    assert "Codex pre-flight failed" in combined, (
        f"Expected 'Codex pre-flight failed' in CLI output, got:\n{combined!r}"
    )
    # Confirm the OLD rejection message is gone.
    assert "not yet implemented" not in combined, (
        f"Old rejection message 'not yet implemented' must not appear. Output:\n{combined!r}"
    )


def test_codex_run_onlycode_preflight_invoked(runner, monkeypatch, tmp_path):
    """build_tools_flags and preflight are invoked for codex_cli + onlycode.

    Structural wiring check: verifies the call chain
    run_command -> runner.preflight() is actually executed.
    """
    preflight_called: list[bool] = []

    def _tracking_preflight(self, mcp_config_path=None):
        preflight_called.append(True)
        raise RuntimeError("stub — stop early")

    monkeypatch.setattr("swebench.runner.CodexRunner.find_binary", lambda self: "/usr/bin/codex")
    monkeypatch.setattr("swebench.runner.CodexRunner.verify_auth", lambda self: None)
    monkeypatch.setattr("swebench.runner.CodexRunner.get_version", lambda self, _: "test")
    monkeypatch.setattr("swebench.runner.CodexRunner.preflight", _tracking_preflight)

    _make_minimal_swe_problem(tmp_path / "problems" / "swe")
    monkeypatch.setattr("swebench.run.repo_root", lambda: tmp_path)

    runner.invoke(
        cli,
        ["run", "--agent-surface", "codex_cli", "--arms", "onlycode",
         "--output-dir", str(tmp_path / "out")],
        catch_exceptions=False,
    )

    assert preflight_called, (
        "CodexRunner.preflight() was never called for codex_cli + onlycode arm. "
        "The rejection guard may have been left in place."
    )


def test_codex_run_onlycode_preflight_ok_proceeds_past_preflight(runner, monkeypatch, tmp_path):
    """codex_cli + onlycode arm proceeds past preflight when it succeeds.

    Wiring assertion: when preflight is a no-op (simulating a valid environment),
    the CLI continues and does not emit a rejection error.

    For codex_cli the MCP env-errors block in run_command is intentionally skipped
    (Codex reads config.toml, not the Claude-format mcp-config.json), so the run
    proceeds directly from preflight into setup.  We stub clone_repo to prevent a
    real network call and let the test confirm only that no rejection/preflight error
    appeared in the output.
    """
    _make_monkeypatched_codex_env(monkeypatch, preflight_raises=False)
    _make_minimal_swe_problem(tmp_path / "problems" / "swe")
    monkeypatch.setattr("swebench.run.repo_root", lambda: tmp_path)
    # Stub clone_repo so no real git clone is attempted — this test only verifies
    # that the CLI does not exit at the preflight/rejection stage.
    import swebench.run as run_mod
    monkeypatch.setattr(run_mod, "clone_repo", lambda repo_slug, dest, **kw: None)

    result = runner.invoke(
        cli,
        [
            "run",
            "--agent-surface", "codex_cli",
            "--arms", "onlycode",
            "--output-dir", str(tmp_path / "out"),
        ],
        catch_exceptions=True,
    )

    output = result.output or ""
    # The run must not be rejected with "not yet implemented".
    assert "not yet implemented" not in output, (
        f"Rejection message must not appear. Output:\n{output!r}"
    )
    # Schema: preflight must have passed (no pre-flight failure message).
    assert "Codex pre-flight failed" not in output, (
        f"Preflight must have passed (no-op), but got pre-flight failure. Output:\n{output!r}"
    )


# ---------------------------------------------------------------------------
# Scenario 2: slice-codex-artifact-code-only-preflight
#
# swebench artifact run --agent-surface codex_cli --arms code_only must reach
# CodexRunner.preflight(), not exit immediately with "not yet implemented".
# ---------------------------------------------------------------------------


def _make_minimal_artifact_task(tmp_path: Path) -> None:
    """Create a minimal artifact task so artifact_run_command gets past task-loading.

    Uses the built-in ``test_fixture`` category which is whitelisted in
    swebench/artifact_loader.py for exactly this use case.
    """
    tasks_root = tmp_path / "problems" / "artifact"
    task_dir = tasks_root / "test_fixture" / "slug1"
    task_dir.mkdir(parents=True)
    workspace = task_dir / "workspace"
    workspace.mkdir()
    grader_dir = task_dir / "grader"
    grader_dir.mkdir()
    (grader_dir / "hidden.py").write_text(
        "def grade(scratch_dir):\n"
        "    return type('R', (), {'score': 1.0, 'verdict': 'pass', 'detail': ''})() \n"
    )
    (task_dir / "task.yaml").write_text(
        "instance_id: test_fixture__slug1\n"
        "category: test_fixture\n"
        "difficulty: easy\n"
        "problem_statement: 'hello'\n"
        "workspace_dir: workspace\n"
        "output_artifact: out.txt\n"
        "hidden_grader: grader/hidden.py\n"
        "reference_output: grader/ref.txt\n"
        "execution_budget:\n"
        "  max_code_runs: 0\n"
        "  max_wall_seconds: 0\n"
    )
    (grader_dir / "ref.txt").write_text("reference\n")


def test_codex_artifact_code_only_calls_preflight_not_rejection(runner, monkeypatch, tmp_path):
    """codex_cli + code_only arm must call preflight(), not emit a rejection error.

    Wiring assertion: the route from ``swebench artifact run`` →
    ``artifact_run_command`` → ``CodexRunner.preflight()`` is connected.
    When preflight raises RuntimeError, CLI emits 'Codex pre-flight failed'.
    """
    _make_monkeypatched_codex_env(monkeypatch, preflight_raises=True)
    _make_minimal_artifact_task(tmp_path)
    monkeypatch.setattr("swebench.artifact_cli.repo_root", lambda: tmp_path)

    result = runner.invoke(
        cli,
        [
            "artifact", "run",
            "--agent-surface", "codex_cli",
            "--arms", "code_only",
            "--output-dir", str(tmp_path / "out"),
        ],
        catch_exceptions=False,
    )

    combined = result.output or ""
    # Schema assertion: non-zero exit when preflight fails.
    assert result.exit_code != 0, (
        f"Expected non-zero exit when preflight fails. Output:\n{combined!r}"
    )
    # Schema assertion: correct error class in output.
    assert "Codex pre-flight failed" in combined, (
        f"Expected 'Codex pre-flight failed' in CLI output. Got:\n{combined!r}"
    )
    # Confirm OLD rejection message is gone.
    assert "not yet implemented" not in combined, (
        f"Old rejection message 'not yet implemented' must not appear. Got:\n{combined!r}"
    )


def test_codex_artifact_code_only_preflight_invoked(runner, monkeypatch, tmp_path):
    """CodexRunner.preflight() is actually called for artifact run + code_only.

    Structural wiring check: verifies the call chain is wired.
    """
    preflight_called: list[bool] = []

    def _tracking_preflight(self, mcp_config_path=None):
        preflight_called.append(True)
        raise RuntimeError("stub — stop early")

    monkeypatch.setattr("swebench.runner.CodexRunner.find_binary", lambda self: "/usr/bin/codex")
    monkeypatch.setattr("swebench.runner.CodexRunner.verify_auth", lambda self: None)
    monkeypatch.setattr("swebench.runner.CodexRunner.get_version", lambda self, _: "test")
    monkeypatch.setattr("swebench.runner.CodexRunner.preflight", _tracking_preflight)

    _make_minimal_artifact_task(tmp_path)
    monkeypatch.setattr("swebench.artifact_cli.repo_root", lambda: tmp_path)

    runner.invoke(
        cli,
        ["artifact", "run",
         "--agent-surface", "codex_cli",
         "--arms", "code_only",
         "--output-dir", str(tmp_path / "out")],
        catch_exceptions=False,
    )

    assert preflight_called, (
        "CodexRunner.preflight() was never called for codex_cli + code_only arm. "
        "The rejection guard may have been left in artifact_cli.py."
    )


# ---------------------------------------------------------------------------
# Scenario 3: slice-codex-run-baseline-no-preflight
#
# swebench run --agent-surface codex_cli --arms baseline must NOT call
# CodexRunner.preflight() (baseline does not need the exec-server bundle).
# ---------------------------------------------------------------------------


def test_codex_run_baseline_does_not_call_preflight(runner, monkeypatch, tmp_path):
    """codex_cli + baseline arm must NOT invoke CodexRunner.preflight().

    Wiring assertion: the exec-server guard in run_command only triggers for
    onlycode/bash_only arms. baseline must pass through without calling preflight
    (which would require the bundle).

    Strategy: monkeypatch preflight to raise AssertionError if called. Then
    use an EMPTY problems dir so run_command exits at "No problem files found"
    (which is AFTER the arm-list/preflight block but BEFORE any actual cloning).
    If preflight were wrongly called for baseline, the AssertionError would
    propagate through Click's CliRunner and fail this test.
    """
    def _bundle_should_not_be_touched(self, mcp_config_path=None):
        raise AssertionError(
            "preflight must NOT be called for codex_cli + baseline arm. "
            "The _CODEX_EXEC_SERVER_ARMS guard in run_command is broken."
        )

    monkeypatch.setattr("swebench.runner.CodexRunner.find_binary", lambda self: "/usr/bin/codex")
    monkeypatch.setattr("swebench.runner.CodexRunner.verify_auth", lambda self: None)
    monkeypatch.setattr("swebench.runner.CodexRunner.get_version", lambda self, _: "test")
    monkeypatch.setattr("swebench.runner.CodexRunner.preflight", _bundle_should_not_be_touched)

    # EMPTY problems dir — run_command exits at "No problem files found"
    # (post arm-list block, pre-cloning), not from a preflight check.
    problems_dir = tmp_path / "problems" / "swe"
    problems_dir.mkdir(parents=True)
    monkeypatch.setattr("swebench.run.repo_root", lambda: tmp_path)

    result = runner.invoke(
        cli,
        [
            "run",
            "--agent-surface", "codex_cli",
            "--arms", "baseline",
            "--output-dir", str(tmp_path / "out"),
        ],
        catch_exceptions=False,
    )

    output = result.output or ""
    # Schema assertion: pre-flight error must not appear.
    assert "Codex pre-flight failed" not in output, (
        f"codex_cli + baseline must not trigger pre-flight error. Output:\n{output!r}"
    )
    # Schema assertion: exit is due to empty problems dir (post-arm-list check).
    assert "No problem files found" in output, (
        f"Expected 'No problem files found' as exit reason (post arm-list check). Output:\n{output!r}"
    )


def test_codex_run_baseline_exit_is_not_from_rejection(runner, monkeypatch, tmp_path):
    """codex_cli + baseline exit reason is not a rejection guard.

    Complementary schema check: confirms exit cause is not a pre-flight guard.
    When baseline arm has no problem files and preflight is not invoked,
    the error should be "No problem files found" — not a pre-flight error.
    """
    _make_monkeypatched_codex_env(monkeypatch, preflight_raises=False)
    # Intentionally do NOT create a problems dir — let it fail on missing files.
    problems_dir = tmp_path / "problems" / "swe"
    problems_dir.mkdir(parents=True)
    monkeypatch.setattr("swebench.run.repo_root", lambda: tmp_path)

    result = runner.invoke(
        cli,
        ["run", "--agent-surface", "codex_cli", "--arms", "baseline",
         "--output-dir", str(tmp_path / "out")],
        catch_exceptions=False,
    )

    output = result.output or ""
    # Schema assertion: pre-flight error must not be present.
    assert "Codex pre-flight failed" not in output, (
        f"codex_cli + baseline must not trigger pre-flight error. Output:\n{output!r}"
    )
    # The exit should be about missing problem files, not the rejection guard.
    assert "not yet implemented" not in output, (
        f"Old rejection message must not appear. Output:\n{output!r}"
    )
    # Schema assertion: the error is about missing problems.
    assert "No problem files found" in output, (
        f"Expected 'No problem files found'. Output:\n{output!r}"
    )


# ---------------------------------------------------------------------------
# Structural wiring: CODEX_NOT_IMPLEMENTED_MSG is gone
# ---------------------------------------------------------------------------


def test_codex_not_implemented_msg_removed():
    """``CODEX_NOT_IMPLEMENTED_MSG`` must not be importable from swebench.runner.

    Acceptance criterion from the plan: the constant is dead code and must be
    removed from runner.py (and its imports from run.py / artifact_cli.py).
    """
    import swebench.runner as runner_mod

    assert not hasattr(runner_mod, "CODEX_NOT_IMPLEMENTED_MSG"), (
        "CODEX_NOT_IMPLEMENTED_MSG must be removed from swebench.runner. "
        "It was a dead-code constant used only for the now-deleted rejection guards."
    )
