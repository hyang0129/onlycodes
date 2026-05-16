"""Component test: run.py → harness.py pre-flight wiring.

Boundary: ``swebench/run.py._run_arm`` calls two real functions from
``swebench/harness.py``:
  1. ``resolve_test_node_ids`` — expands bare sympy test names to node IDs.
  2. ``run_preflight_collect`` — runs ``pytest --collect-only`` and returns
     ``(False, output)`` when zero items are collected.

Both functions are exercised as their *real* harness implementations — no
harness-level doubles.  The only seam doubled is ``subprocess.run`` inside
the harness module (an I/O boundary), and the git/Claude/test-runner I/O
boundaries in ``run.py`` (``git_reset``, ``run_claude``, ``run_tests``).

These tests assert the cross-module contract that:
  - when preflight returns False via the real harness path, ``_run_arm``
    writes ``env_fail`` to both output files and returns ``"env_fail"``.
  - when preflight returns True via the real harness path, ``_run_arm``
    continues past the pre-flight gate and invokes the agent.

The critical difference from the unit tests in ``test_run_preflight.py``
(which double ``run_mod.run_preflight_collect`` entirely) is that *here*
the real harness ``run_preflight_collect`` implementation runs, so if
``run.py`` ever stops importing or calling the harness function correctly
these tests will catch the regression.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import swebench.harness as _harness_mod
from swebench.models import Problem
from swebench import run as run_mod


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

INSTANCE = "sympy__sympy-14180"
ARM = "baseline"
RUN_IDX = 1


def _make_problem(tmp_path: Path, test_cmd: str = "python -m pytest test_bare_name") -> Problem:
    """Build a minimal Problem for the env_fail code path."""
    return Problem(
        instance_id=INSTANCE,
        repo_slug="sympy/sympy",
        base_commit="abc123",
        test_cmd=test_cmd,
        problem_statement="dummy",
        patch_file=None,
        added_at="2026-01-01",
        hf_split="test",
    )


def _make_dirs(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()
    (venv_dir / "bin").mkdir()
    (venv_dir / "bin" / "python").write_text("#!/bin/sh\nexec python3 \"$@\"\n")
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    return str(repo_dir), str(venv_dir), str(results_dir)


class _FakeCompleted:
    """Minimal stand-in for ``subprocess.CompletedProcess``."""
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ---------------------------------------------------------------------------
# Boundary 1: real harness.run_preflight_collect returns False → env_fail
# ---------------------------------------------------------------------------


@pytest.mark.component
class TestRunArmPrefailViaRealHarness:
    """
    _run_arm reads its preflight result from the real harness.run_preflight_collect.
    When the real function reports 0 items collected, _run_arm must write
    env_fail to disk and return 'env_fail'.
    """

    def test_env_fail_files_written_via_real_harness_path(
        self, monkeypatch, tmp_path: Path
    ):
        """The real run_preflight_collect is wired into _run_arm.

        We double subprocess.run inside the harness to return 'no tests ran'
        (exit 5).  Everything else — the harness preflight logic, the run.py
        env_fail write path — runs for real.
        """
        repo_dir, venv_dir, results_dir = _make_dirs(tmp_path)

        # Double subprocess.run inside the harness (I/O seam only).
        # Return exit-5 / no items collected for pytest --collect-only calls,
        # and exit-0 for git calls so git_reset doesn't blow up.
        def _fake_subprocess_run(cmd, **kw):
            # git commands — succeed silently.
            if isinstance(cmd, list) and cmd and cmd[0] == "git":
                return _FakeCompleted(returncode=0, stdout="", stderr="")
            # pytest --collect-only call from run_preflight_collect/resolve.
            return _FakeCompleted(
                returncode=5,
                stdout="no tests ran in 0.05s\n",
                stderr="",
            )

        monkeypatch.setattr(_harness_mod.subprocess, "run", _fake_subprocess_run)

        # Double the I/O seams in run.py that are not part of this boundary.
        monkeypatch.setattr(run_mod, "git_reset", lambda *a, **kw: None)

        def _boom_run_claude(**kw):  # pragma: no cover
            raise AssertionError("run_claude must not be called when preflight fails")

        monkeypatch.setattr(run_mod, "run_claude", _boom_run_claude)

        problem = _make_problem(tmp_path)

        verdict = run_mod._run_arm(
            problem=problem,
            arm=ARM,
            run_idx=RUN_IDX,
            repo_dir=repo_dir,
            venv_dir=venv_dir,
            results_dir=results_dir,
            agent_binary="/usr/bin/claude",
            mcp_config_path=str(tmp_path / "mcp.json"),
            root=tmp_path,
        )

        # _run_arm must return "env_fail".
        assert verdict == "env_fail", f"Expected 'env_fail', got {verdict!r}"

        # The _test.txt must end with "env_fail".
        test_txt = Path(results_dir) / f"{INSTANCE}_{ARM}_run{RUN_IDX}_test.txt"
        assert test_txt.exists(), "_test.txt was not written"
        last_line = [ln for ln in test_txt.read_text().splitlines() if ln.strip()][-1]
        assert last_line.strip() == "env_fail", (
            f"Expected last non-empty line 'env_fail'; got {last_line!r}"
        )

        # The .jsonl must contain a meta record with verdict=env_fail.
        jsonl = Path(results_dir) / f"{INSTANCE}_{ARM}_run{RUN_IDX}.jsonl"
        assert jsonl.exists(), ".jsonl was not written"
        record = json.loads(jsonl.read_text().splitlines()[0])
        assert record["verdict"] == "env_fail", (
            f"jsonl meta record has wrong verdict: {record}"
        )
        assert record["instance_id"] == INSTANCE

    def test_env_fail_jsonl_has_required_fields(self, monkeypatch, tmp_path: Path):
        """The meta record written by the real env_fail path must carry all
        fields that downstream tools (analyze, summary, _is_triple_complete) need."""
        repo_dir, venv_dir, results_dir = _make_dirs(tmp_path)

        def _fake_subprocess_run(cmd, **kw):
            if isinstance(cmd, list) and cmd and cmd[0] == "git":
                return _FakeCompleted(0)
            return _FakeCompleted(5, stdout="collected 0 items\n")

        monkeypatch.setattr(_harness_mod.subprocess, "run", _fake_subprocess_run)
        monkeypatch.setattr(run_mod, "git_reset", lambda *a, **kw: None)
        monkeypatch.setattr(run_mod, "run_claude", lambda **kw: None)

        problem = _make_problem(tmp_path)
        run_mod._run_arm(
            problem=problem,
            arm=ARM,
            run_idx=RUN_IDX,
            repo_dir=repo_dir,
            venv_dir=venv_dir,
            results_dir=results_dir,
            agent_binary="/usr/bin/claude",
            mcp_config_path=str(tmp_path / "mcp.json"),
            root=tmp_path,
        )

        jsonl = Path(results_dir) / f"{INSTANCE}_{ARM}_run{RUN_IDX}.jsonl"
        record = json.loads(jsonl.read_text().splitlines()[0])

        # Required fields for downstream tools.
        assert record.get("type") == "meta"
        assert record.get("verdict") == "env_fail"
        assert record.get("instance_id") == INSTANCE
        assert record.get("arm") == ARM
        assert record.get("run") == RUN_IDX

    def test_preflight_output_embedded_in_test_txt(self, monkeypatch, tmp_path: Path):
        """The raw pytest --collect-only output must appear in the _test.txt body."""
        repo_dir, venv_dir, results_dir = _make_dirs(tmp_path)

        preflight_output = "no tests ran in 0.07s\n"

        def _fake_subprocess_run(cmd, **kw):
            if isinstance(cmd, list) and cmd and cmd[0] == "git":
                return _FakeCompleted(0)
            return _FakeCompleted(5, stdout=preflight_output)

        monkeypatch.setattr(_harness_mod.subprocess, "run", _fake_subprocess_run)
        monkeypatch.setattr(run_mod, "git_reset", lambda *a, **kw: None)
        monkeypatch.setattr(run_mod, "run_claude", lambda **kw: None)

        problem = _make_problem(tmp_path)
        run_mod._run_arm(
            problem=problem,
            arm=ARM,
            run_idx=RUN_IDX,
            repo_dir=repo_dir,
            venv_dir=venv_dir,
            results_dir=results_dir,
            agent_binary="/usr/bin/claude",
            mcp_config_path=str(tmp_path / "mcp.json"),
            root=tmp_path,
        )

        test_txt = Path(results_dir) / f"{INSTANCE}_{ARM}_run{RUN_IDX}_test.txt"
        body = test_txt.read_text()
        assert "no tests ran" in body, (
            f"Preflight output not embedded in _test.txt:\n{body}"
        )


# ---------------------------------------------------------------------------
# Boundary 1b: agent_binary parameter propagates into env_fail .jsonl record
# ---------------------------------------------------------------------------


@pytest.mark.component
class TestRunArmEnvFailAgentBinaryPropagation:
    """
    Regression test for the rename bug (Issue #248):
    _run_arm must write the agent_binary *argument value* into the env_fail
    meta record — not a stale local name that no longer exists.

    Uses a direct monkeypatch of run_preflight_collect (not subprocess.run)
    so this test drives the dict-literal path with known argument values and
    would have caught the claude_binary → agent_binary rename miss.
    """

    def test_agent_binary_value_written_to_jsonl(self, monkeypatch, tmp_path: Path):
        """agent_binary argument must appear verbatim in the env_fail .jsonl record."""
        repo_dir, venv_dir, results_dir = _make_dirs(tmp_path)

        monkeypatch.setattr(run_mod, "git_reset", lambda *a, **kw: None)
        monkeypatch.setattr(run_mod, "resolve_test_node_ids", lambda cmd, **kw: cmd)
        monkeypatch.setattr(
            run_mod, "run_preflight_collect", lambda **kw: (False, "0 items collected")
        )

        def _boom_run_claude(**kw):  # pragma: no cover
            raise AssertionError("run_claude must not be called when preflight fails")

        monkeypatch.setattr(run_mod, "run_claude", _boom_run_claude)

        problem = _make_problem(tmp_path)
        verdict = run_mod._run_arm(
            problem=problem,
            arm=ARM,
            run_idx=RUN_IDX,
            repo_dir=repo_dir,
            venv_dir=venv_dir,
            results_dir=results_dir,
            agent_binary="/fake/binary",
            mcp_config_path=str(tmp_path / "mcp.json"),
            root=tmp_path,
        )

        assert verdict == "env_fail"

        jsonl = Path(results_dir) / f"{INSTANCE}_{ARM}_run{RUN_IDX}.jsonl"
        assert jsonl.exists(), ".jsonl was not written"
        record = json.loads(jsonl.read_text().splitlines()[0])
        assert record["verdict"] == "env_fail"
        assert record["agent_binary"] == "/fake/binary", (
            f"agent_binary not propagated correctly into meta record: {record}"
        )

    def test_test_txt_ends_with_env_fail(self, monkeypatch, tmp_path: Path):
        """_test.txt must exist and its last non-empty line must be 'env_fail'."""
        repo_dir, venv_dir, results_dir = _make_dirs(tmp_path)

        monkeypatch.setattr(run_mod, "git_reset", lambda *a, **kw: None)
        monkeypatch.setattr(run_mod, "resolve_test_node_ids", lambda cmd, **kw: cmd)
        monkeypatch.setattr(
            run_mod, "run_preflight_collect", lambda **kw: (False, "no tests ran\n")
        )
        monkeypatch.setattr(run_mod, "run_claude", lambda **kw: None)

        problem = _make_problem(tmp_path)
        run_mod._run_arm(
            problem=problem,
            arm=ARM,
            run_idx=RUN_IDX,
            repo_dir=repo_dir,
            venv_dir=venv_dir,
            results_dir=results_dir,
            agent_binary="/fake/binary",
            mcp_config_path=str(tmp_path / "mcp.json"),
            root=tmp_path,
        )

        test_txt = Path(results_dir) / f"{INSTANCE}_{ARM}_run{RUN_IDX}_test.txt"
        assert test_txt.exists(), "_test.txt was not written"
        last_line = [ln for ln in test_txt.read_text().splitlines() if ln.strip()][-1]
        assert last_line.strip() == "env_fail", (
            f"Expected last non-empty line 'env_fail'; got {last_line!r}"
        )


# ---------------------------------------------------------------------------
# Boundary 2: real harness.resolve_test_node_ids feeds into run_preflight_collect
# ---------------------------------------------------------------------------


@pytest.mark.component
class TestRunArmResolverFeedsIntoPreflightViaRealHarness:
    """
    _run_arm calls resolve_test_node_ids first, then passes the result to
    run_preflight_collect.  For non-sympy repos, the resolver must return
    the original command unchanged; for sympy, it calls subprocess.run once
    to expand bare names.

    Both functions run as real harness code — only subprocess.run is doubled.
    """

    def test_non_sympy_repo_skips_resolver_subprocess(
        self, monkeypatch, tmp_path: Path
    ):
        """For non-sympy repos, no subprocess.run call originates from the resolver."""
        repo_dir, venv_dir, results_dir = _make_dirs(tmp_path)

        resolver_calls: list[list] = []

        def _recording_subprocess_run(cmd, **kw):
            if isinstance(cmd, list) and "--collect-only" in cmd:
                resolver_calls.append(cmd)
                return _FakeCompleted(5, stdout="no tests ran\n")
            return _FakeCompleted(0)

        monkeypatch.setattr(_harness_mod.subprocess, "run", _recording_subprocess_run)
        monkeypatch.setattr(run_mod, "git_reset", lambda *a, **kw: None)
        monkeypatch.setattr(run_mod, "run_claude", lambda **kw: None)

        problem = Problem(
            instance_id="django__django-16379",
            repo_slug="django/django",
            base_commit="abc",
            test_cmd="python -m pytest tests/test_foo.py",
            problem_statement="dummy",
            patch_file=None,
            added_at="2026-01-01",
            hf_split="test",
        )

        run_mod._run_arm(
            problem=problem,
            arm="baseline",
            run_idx=1,
            repo_dir=repo_dir,
            venv_dir=venv_dir,
            results_dir=results_dir,
            agent_binary="/usr/bin/claude",
            mcp_config_path=str(tmp_path / "mcp.json"),
            root=tmp_path,
        )

        # The resolver must not have triggered a subprocess.run --collect-only call
        # on its own (i.e., the preflight may call it once, but resolver adds 0).
        # The preflight itself calls subprocess.run once; the resolver adds 0.
        # Assert that no call was made for the resolver (all calls come from preflight).
        # Both paths are via the real harness; we just record calls.
        assert len(resolver_calls) == 1, (
            f"Expected exactly 1 --collect-only call (from preflight only, not resolver); "
            f"got {len(resolver_calls)}"
        )

    def test_sympy_bare_name_triggers_resolver_subprocess_then_preflight(
        self, monkeypatch, tmp_path: Path
    ):
        """For sympy repos with a bare test name, the resolver fires subprocess.run
        FIRST to expand the name; the preflight then uses the expanded node ID."""
        repo_dir, venv_dir, results_dir = _make_dirs(tmp_path)

        collect_only_calls: list[list] = []
        call_count = {"n": 0}

        def _recording_subprocess_run(cmd, **kw):
            if isinstance(cmd, list) and "--collect-only" in cmd:
                collect_only_calls.append(list(cmd))
                call_count["n"] += 1
                if call_count["n"] == 1:
                    # First call = resolver expanding bare name → return a node ID.
                    return _FakeCompleted(
                        0,
                        stdout=(
                            "sympy/printing/tests/test_latex.py::test_latex_log\n"
                            "1 test collected in 0.42s\n"
                        ),
                    )
                else:
                    # Second call = preflight on the now-expanded command.
                    return _FakeCompleted(
                        0,
                        stdout="sympy/printing/tests/test_latex.py::test_latex_log\n1 test collected\n",
                    )
            return _FakeCompleted(0)

        monkeypatch.setattr(_harness_mod.subprocess, "run", _recording_subprocess_run)
        monkeypatch.setattr(run_mod, "git_reset", lambda *a, **kw: None)

        # Agent invoked (preflight passes) — stub it out.
        invoked = {"count": 0}

        class _StubRunner:
            surface = "claude_code"

            def build_tools_flags(self, arm, cfg):
                return []

            def get_version(self, binary):
                return "stub"

            def extract_metadata(self, path):
                return (None, None)

            def invoke(self, **kw):
                invoked["count"] += 1
                Path(kw["result_file"]).write_text(
                    '{"type":"result","total_cost_usd":0.0,"num_turns":0}\n'
                )

        def _stub_run_tests(**kw):
            Path(kw["result_file"]).write_text("PASS\n")
            return "PASS"

        monkeypatch.setattr(run_mod, "run_tests", _stub_run_tests)

        problem = Problem(
            instance_id="sympy__sympy-14180",
            repo_slug="sympy/sympy",
            base_commit="abc",
            test_cmd="python -m pytest test_latex_log",
            problem_statement="dummy",
            patch_file=None,
            added_at="2026-01-01",
            hf_split="test",
        )

        verdict = run_mod._run_arm(
            problem=problem,
            arm="baseline",
            run_idx=1,
            repo_dir=repo_dir,
            venv_dir=venv_dir,
            results_dir=results_dir,
            agent_binary="/usr/bin/claude",
            mcp_config_path=str(tmp_path / "mcp.json"),
            root=tmp_path,
            runner=_StubRunner(),
        )

        # Two --collect-only subprocess.run calls expected: one from the resolver,
        # one from the preflight.
        assert call_count["n"] == 2, (
            f"Expected 2 --collect-only subprocess calls (resolver + preflight); "
            f"got {call_count['n']}. Calls: {collect_only_calls}"
        )
        # The second preflight call must see the expanded node ID in its args,
        # not the bare name — confirming resolver output feeds into preflight.
        assert any(
            "sympy/printing/tests/test_latex.py::test_latex_log" in arg
            for arg in collect_only_calls[1]
        ), (
            f"Preflight call did not receive expanded node ID. "
            f"Second call args: {collect_only_calls[1]}"
        )
        # Agent was invoked (preflight passed).
        assert invoked["count"] == 1
        assert verdict == "PASS"
