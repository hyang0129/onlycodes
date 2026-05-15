"""Tests for per-instance test-env-var injection (Issue #246).

Covers:
  (a) run_tests() passes no env= to subprocess when extra_env is None/absent,
  (b) run_tests() merges extra_env into os.environ and passes env= when supplied,
  (c) _INSTANCE_ENV entry for astropy__astropy-6938 sets PYTEST_CACHE_DIR,
  (d) _run_arm looks up _INSTANCE_ENV and passes it through to run_tests().
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import swebench.harness as _harness_mod
from swebench.harness import _INSTANCE_ENV, run_tests
from swebench import run as run_mod
from swebench.models import Problem


# ---------------------------------------------------------------------------
# Unit tests for run_tests() extra_env parameter
# ---------------------------------------------------------------------------


class TestRunTestsExtraEnv:
    """run_tests passes env correctly to subprocess.run."""

    def _write_dummy_result(self, result_file: str) -> None:
        with open(result_file, "w") as f:
            f.write("PASS\n")

    def test_no_extra_env_passes_none_to_subprocess(
        self, monkeypatch, tmp_path: Path
    ):
        """When extra_env is not supplied, subprocess.run receives env=None (inherits)."""
        captured: list[dict] = []

        def _fake_run(cmd, **kw):
            captured.append({"env": kw.get("env")})
            self._write_dummy_result(kw["stdout"].name if hasattr(kw.get("stdout"), "name") else str(tmp_path / "r.txt"))
            return SimpleNamespace(returncode=0)

        # patch open so result_file writes succeed, and patch subprocess.run
        monkeypatch.setattr(_harness_mod.subprocess, "run", _fake_run)

        result_file = str(tmp_path / "result.txt")
        Path(result_file).write_text("")

        # Use a passthrough fake to avoid actual subprocess
        calls: list[dict] = []

        def _recording_run(cmd, **kw):
            calls.append(kw)
            # Write a PASS result to the file handle
            out = kw.get("stdout")
            if hasattr(out, "write"):
                out.write("PASS\n")
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(_harness_mod.subprocess, "run", _recording_run)

        venv_dir = str(tmp_path / "venv")
        (tmp_path / "venv" / "bin").mkdir(parents=True)
        (tmp_path / "venv" / "bin" / "python").write_text("#!/bin/sh\n")

        run_tests(
            repo_dir=str(tmp_path),
            test_cmd="python -m pytest test_foo.py",
            venv_dir=venv_dir,
            result_file=result_file,
        )

        assert len(calls) == 1
        assert calls[0].get("env") is None, (
            "env should be None (inherit) when extra_env is not supplied"
        )

    def test_extra_env_merged_into_subprocess_env(
        self, monkeypatch, tmp_path: Path
    ):
        """When extra_env is supplied, subprocess.run receives a merged env dict."""
        calls: list[dict] = []

        def _recording_run(cmd, **kw):
            calls.append(kw)
            out = kw.get("stdout")
            if hasattr(out, "write"):
                out.write("PASS\n")
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(_harness_mod.subprocess, "run", _recording_run)

        venv_dir = str(tmp_path / "venv")
        (tmp_path / "venv" / "bin").mkdir(parents=True)
        (tmp_path / "venv" / "bin" / "python").write_text("#!/bin/sh\n")
        result_file = str(tmp_path / "result.txt")

        run_tests(
            repo_dir=str(tmp_path),
            test_cmd="python -m pytest test_foo.py",
            venv_dir=venv_dir,
            result_file=result_file,
            extra_env={"PYTEST_CACHE_DIR": "/tmp/custom_cache"},
        )

        assert len(calls) == 1
        env_passed = calls[0].get("env")
        assert env_passed is not None, "env must be a dict when extra_env is supplied"
        assert env_passed.get("PYTEST_CACHE_DIR") == "/tmp/custom_cache"
        # Existing env vars must be preserved
        assert "PATH" in env_passed, "PATH must be preserved from os.environ"

    def test_extra_env_overrides_existing_var(
        self, monkeypatch, tmp_path: Path
    ):
        """extra_env values override same-named variables from os.environ."""
        calls: list[dict] = []

        def _recording_run(cmd, **kw):
            calls.append(kw)
            out = kw.get("stdout")
            if hasattr(out, "write"):
                out.write("PASS\n")
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(_harness_mod.subprocess, "run", _recording_run)
        monkeypatch.setenv("MY_VAR", "original")

        venv_dir = str(tmp_path / "venv")
        (tmp_path / "venv" / "bin").mkdir(parents=True)
        (tmp_path / "venv" / "bin" / "python").write_text("#!/bin/sh\n")
        result_file = str(tmp_path / "result.txt")

        run_tests(
            repo_dir=str(tmp_path),
            test_cmd="python -m pytest test_foo.py",
            venv_dir=venv_dir,
            result_file=result_file,
            extra_env={"MY_VAR": "overridden"},
        )

        env_passed = calls[0]["env"]
        assert env_passed["MY_VAR"] == "overridden"


# ---------------------------------------------------------------------------
# Unit test: _INSTANCE_ENV table correctness
# ---------------------------------------------------------------------------


class TestInstanceEnvTable:
    def test_astropy_6938_has_pytest_cache_dir(self):
        entry = _INSTANCE_ENV.get("astropy__astropy-6938")
        assert entry is not None, "_INSTANCE_ENV missing astropy__astropy-6938"
        assert "PYTEST_CACHE_DIR" in entry, "PYTEST_CACHE_DIR must be set for astropy-6938"
        assert entry["PYTEST_CACHE_DIR"], "PYTEST_CACHE_DIR value must be non-empty"

    def test_all_values_are_non_empty_strings(self):
        for instance_id, env_dict in _INSTANCE_ENV.items():
            for key, val in env_dict.items():
                assert isinstance(val, str) and val, (
                    f"_INSTANCE_ENV[{instance_id!r}][{key!r}] is empty or non-string"
                )


# ---------------------------------------------------------------------------
# Component test: _run_arm passes _INSTANCE_ENV to run_tests
# ---------------------------------------------------------------------------


class TestRunArmPassesInstanceEnv:
    """_run_arm must look up _INSTANCE_ENV and forward it to run_tests."""

    def _make_problem(self, instance_id: str = "astropy__astropy-6938") -> Problem:
        return Problem(
            instance_id=instance_id,
            repo_slug="astropy/astropy",
            base_commit="abc123",
            test_cmd="python -m pytest astropy/tests/test_foo.py",
            problem_statement="dummy",
            patch_file=None,
            added_at="2026-01-01",
            hf_split="test",
        )

    def _make_dirs(self, tmp_path: Path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        venv_dir = tmp_path / "venv"
        (venv_dir / "bin").mkdir(parents=True)
        (venv_dir / "bin" / "python").write_text("#!/bin/sh\nexec python3 \"$@\"\n")
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        return str(repo_dir), str(venv_dir), str(results_dir)

    @pytest.mark.component
    def test_instance_env_forwarded_to_run_tests(
        self, monkeypatch, tmp_path: Path
    ):
        """_run_arm must pass _INSTANCE_ENV[instance_id] as extra_env to run_tests."""
        repo_dir, venv_dir, results_dir = self._make_dirs(tmp_path)
        captured_extra_env: list = []

        def _stub_run_tests(**kw):
            captured_extra_env.append(kw.get("extra_env"))
            Path(kw["result_file"]).write_text("PASS\n")
            return "PASS"

        monkeypatch.setattr(run_mod, "git_reset", lambda *a, **kw: None)
        monkeypatch.setattr(run_mod, "run_preflight_collect", lambda **kw: (True, "1 test collected"))
        monkeypatch.setattr(run_mod, "run_claude", lambda **kw: None)
        monkeypatch.setattr(run_mod, "run_tests", _stub_run_tests)

        # Stub the runner so _run_arm doesn't need a real agent binary
        class _StubRunner:
            surface = "claude_code"

            def build_tools_flags(self, arm, cfg):
                return []

            def get_version(self, binary):
                return "stub"

            def extract_metadata(self, path):
                return (None, None)

            def invoke(self, **kw):
                Path(kw["result_file"]).write_text(
                    '{"type":"meta","verdict":"PASS","instance_id":"astropy__astropy-6938",'
                    '"arm":"baseline","run":1}\n'
                )

        problem = self._make_problem()
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
            runner=_StubRunner(),
        )

        assert len(captured_extra_env) == 1, "run_tests must have been called once"
        extra = captured_extra_env[0]
        assert extra is not None, (
            "extra_env must be a dict for astropy__astropy-6938, not None"
        )
        assert extra.get("PYTEST_CACHE_DIR"), (
            f"PYTEST_CACHE_DIR must be set in extra_env; got {extra!r}"
        )

    @pytest.mark.component
    def test_instance_without_env_entry_passes_none(
        self, monkeypatch, tmp_path: Path
    ):
        """For instances not in _INSTANCE_ENV, extra_env must be None."""
        repo_dir, venv_dir, results_dir = self._make_dirs(tmp_path)
        captured_extra_env: list = []

        def _stub_run_tests(**kw):
            captured_extra_env.append(kw.get("extra_env"))
            Path(kw["result_file"]).write_text("PASS\n")
            return "PASS"

        monkeypatch.setattr(run_mod, "git_reset", lambda *a, **kw: None)
        monkeypatch.setattr(run_mod, "run_preflight_collect", lambda **kw: (True, "1 test collected"))
        monkeypatch.setattr(run_mod, "run_claude", lambda **kw: None)
        monkeypatch.setattr(run_mod, "run_tests", _stub_run_tests)

        class _StubRunner:
            surface = "claude_code"

            def build_tools_flags(self, arm, cfg):
                return []

            def get_version(self, binary):
                return "stub"

            def extract_metadata(self, path):
                return (None, None)

            def invoke(self, **kw):
                Path(kw["result_file"]).write_text(
                    '{"type":"meta","verdict":"PASS","instance_id":"django__django-16379",'
                    '"arm":"baseline","run":1}\n'
                )

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
            runner=_StubRunner(),
        )

        assert len(captured_extra_env) == 1
        assert captured_extra_env[0] is None, (
            "extra_env must be None for instances not in _INSTANCE_ENV"
        )
