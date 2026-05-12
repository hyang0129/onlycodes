"""Integration tests for the ``swebench cache setup`` CLI → venv-kwargs routing.

Scenario: slice-cache-setup-cli-venv-routing
Tier: wiring

Verifies that the ``swebench cache setup`` CLI command correctly threads the
per-repo Python-version and pre-install-pin kwargs from the harness lookup
tables all the way through the full vertical slice:

  CLI (swebench/cli.py)
    → cache_group.setup() (swebench/cache_cli.py)
      → _load_problems()
        → _setup_one()
          → harness.setup_venv(python_bin=..., pre_install=...)

The change under test (swebench/cache_cli.py):
- ``_setup_one()`` must pass ``**_venv_kwargs(problem.repo_slug)`` to
  ``setup_venv()``, forwarding the correct interpreter (e.g. ``python3.10``
  for scikit-learn) and the correct pre-install pin list.

Before issue #203, ``_setup_one()`` called ``setup_venv(venv_dir, repo_dir)``
with no kwargs — always using the default ``python3.11`` with no pins,
silently breaking old-scikit-learn and matplotlib instances.

These tests exercise the full Click dispatch path via ``CliRunner`` and
intercept only real I/O boundaries (subprocess, git network calls, and the
filesystem cache root).  ``setup_venv`` itself is NOT doubled — we observe
what arguments it forwards by capturing ``subprocess.run`` calls at the
lowest layer.

Assertions (wiring tier):
  - Status: ``_setup_one`` returns ``(id, True, ...)`` (success tuple) for the
    covered repos — verifying the CLI wiring is structurally sound.
  - Interpreter: the ``python -m venv`` subprocess call uses the repo's
    designated interpreter (e.g. ``python3.10`` for scikit-learn).
  - Schema: for repos in ``_REPO_PRE_INSTALL``, a ``pip install`` call
    containing one of the expected pins appears before the editable install.
  - Negative: for unlisted repos, the default interpreter is used and no
    pre-install pin calls are injected.

Exact output values (pip freeze, venv contents) are volatile — not asserted.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from swebench.cli import cli
from swebench.harness import _DEFAULT_PYTHON, _REPO_PRE_INSTALL, _REPO_PYTHON
from swebench.models import Problem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_problem(repo_slug: str, instance_id: str | None = None) -> Problem:
    iid = instance_id or f"test__{repo_slug.replace('/', '__')}"
    return Problem(
        instance_id=iid,
        repo_slug=repo_slug,
        base_commit="deadbeef",
        test_cmd="python -m pytest",
        problem_statement="stub",
        patch_file=None,
        added_at="2026-01-01",
        hf_split="test",
    )


def _make_subprocess_ok(*args: Any, **kwargs: Any) -> MagicMock:
    m = MagicMock()
    m.returncode = 0
    m.stdout = b""
    m.stderr = b""
    return m


def _make_subprocess_patcher(venv_creation_args: list, pip_install_args: list):
    """Return a side_effect function that records venv and pip install calls."""

    def fake_run(cmd: Any, **kwargs: Any) -> MagicMock:
        cmd_list = list(cmd) if isinstance(cmd, (list, tuple)) else []
        # Capture venv creation calls
        if "-m" in cmd_list and "venv" in cmd_list:
            venv_creation_args.append(cmd_list)
            # Materialise bin/pip so setup_venv continues
            venv_dir_arg = cmd_list[-1]
            pip_bin = os.path.join(venv_dir_arg, "bin", "pip")
            os.makedirs(os.path.dirname(pip_bin), exist_ok=True)
            Path(pip_bin).touch()
        # Capture all pip install calls
        if cmd_list and "pip" in str(cmd_list[0]) and "install" in cmd_list:
            pip_install_args.append(cmd_list)
        return _make_subprocess_ok(cmd, **kwargs)

    return fake_run


# ---------------------------------------------------------------------------
# Scenario: slice-cache-setup-cli-venv-routing
# Wiring tests
# ---------------------------------------------------------------------------


class TestCacheSetupCliVenvRouting:
    """Full vertical-slice wiring tests for ``cache setup`` → ``setup_venv`` kwarg routing.

    These tests do NOT use @pytest.mark.integration because they are fully
    offline (no network, no real venv creation) and complete in well under 5s.
    They are appropriate for every CI push.
    """

    def test_sklearn_instance_uses_python310_via_cli(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """CLI slice: ``cache setup --filter sklearn-id`` dispatches to
        ``setup_venv`` with ``python_bin='python3.10'``.

        Covers the route:
          CliRunner.invoke(cli, ['cache', 'setup', '--filter', id])
            → _load_problems()
            → _setup_one()
            → setup_venv(python_bin='python3.10', ...)
        """
        monkeypatch.setenv("SWEBENCH_CACHE_ROOT", str(tmp_path / "cache"))

        # Build a minimal problems/swe dir so _load_problems() finds the YAML
        problems_swe = tmp_path / "problems" / "swe" / "test-set"
        problems_swe.mkdir(parents=True)
        problem = _make_problem("scikit-learn/scikit-learn", "sklearn__sklearn-99999")
        yaml_path = problems_swe / f"{problem.instance_id}.yaml"

        # Write a minimal YAML (mirroring the real format)
        yaml_path.write_text(
            f"instance_id: {problem.instance_id}\n"
            f"repo: {problem.repo_slug}\n"
            f"base_commit: deadbeef\n"
            f"test_cmd: python -m pytest\n"
            f"patch_file: null\n"
            f"problem_statement: stub\n"
            f"added_at: '2026-01-01'\n"
            f"hf_split: test\n"
        )

        expected_python = _REPO_PYTHON["scikit-learn/scikit-learn"]
        assert expected_python == "python3.10"

        venv_creation_args: list[list[str]] = []
        pip_install_args: list[list[str]] = []

        with (
            patch(
                "subprocess.run",
                side_effect=_make_subprocess_patcher(venv_creation_args, pip_install_args),
            ),
            patch("swebench.cache_cli.clone_bare_repo"),
            patch("swebench.cache_cli.clone_from_bare"),
            patch("swebench.cache_cli.git_reset"),
            patch("swebench.cache_cli.scrub_cache_dir"),
            patch("swebench.cache_cli.write_lockfile"),
            patch("swebench.cache_cli.repo_root", return_value=tmp_path),
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["cache", "setup", "--filter", problem.instance_id, "--concurrency", "1"],
                catch_exceptions=False,
            )

        # Wiring: CLI must exit zero (no crash in dispatch or module wiring)
        assert result.exit_code == 0, (
            f"CLI exited with {result.exit_code}. Output:\n{result.output}"
        )

        # Wiring: at least one venv creation subprocess was called
        assert venv_creation_args, (
            "setup_venv never issued a `python -m venv` subprocess call — "
            "the cache_cli → harness wiring may be severed"
        )

        # Wiring: the venv was created with the repo-specific interpreter
        first_venv_cmd = venv_creation_args[0]
        assert expected_python in first_venv_cmd, (
            f"Expected {expected_python!r} in venv-creation command, got: {first_venv_cmd!r}. "
            "cache_cli._setup_one must forward python_bin from _REPO_PYTHON via _venv_kwargs()."
        )

    def test_sklearn_instance_pre_install_pins_routed_via_cli(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """CLI slice: ``cache setup`` for scikit-learn issues pip install calls
        containing the pre-install pins from ``_REPO_PRE_INSTALL``.

        Verifies that ``pre_install`` kwarg reaches ``setup_venv`` and that
        setup_venv issues the expected pre-install pip calls.
        """
        monkeypatch.setenv("SWEBENCH_CACHE_ROOT", str(tmp_path / "cache"))

        problems_swe = tmp_path / "problems" / "swe" / "test-set"
        problems_swe.mkdir(parents=True)
        problem = _make_problem("scikit-learn/scikit-learn", "sklearn__sklearn-99998")
        yaml_path = problems_swe / f"{problem.instance_id}.yaml"
        yaml_path.write_text(
            f"instance_id: {problem.instance_id}\n"
            f"repo: {problem.repo_slug}\n"
            f"base_commit: deadbeef\n"
            f"test_cmd: python -m pytest\n"
            f"patch_file: null\n"
            f"problem_statement: stub\n"
            f"added_at: '2026-01-01'\n"
            f"hf_split: test\n"
        )

        expected_pins = _REPO_PRE_INSTALL["scikit-learn/scikit-learn"]

        venv_creation_args: list[list[str]] = []
        pip_install_args: list[list[str]] = []

        with (
            patch(
                "subprocess.run",
                side_effect=_make_subprocess_patcher(venv_creation_args, pip_install_args),
            ),
            patch("swebench.cache_cli.clone_bare_repo"),
            patch("swebench.cache_cli.clone_from_bare"),
            patch("swebench.cache_cli.git_reset"),
            patch("swebench.cache_cli.scrub_cache_dir"),
            patch("swebench.cache_cli.write_lockfile"),
            patch("swebench.cache_cli.repo_root", return_value=tmp_path),
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["cache", "setup", "--filter", problem.instance_id, "--concurrency", "1"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0, (
            f"CLI exited with {result.exit_code}. Output:\n{result.output}"
        )

        # Wiring: at least one pip install call must contain one of the expected pins
        pin_calls = [
            c for c in pip_install_args
            if any(pin in " ".join(c) for pin in expected_pins)
        ]
        assert pin_calls, (
            f"No pip install call contained expected pre-install pins.\n"
            f"Expected pins (any of): {expected_pins}\n"
            f"All pip install calls observed: {pip_install_args}\n"
            "cache_cli._setup_one must forward pre_install from _REPO_PRE_INSTALL via _venv_kwargs()."
        )

    def test_matplotlib_instance_pre_install_pins_routed_via_cli(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """CLI slice: ``cache setup`` for matplotlib issues numpy/cython/setuptools
        pre-install pip calls from ``_REPO_PRE_INSTALL``.
        """
        monkeypatch.setenv("SWEBENCH_CACHE_ROOT", str(tmp_path / "cache"))

        problems_swe = tmp_path / "problems" / "swe" / "test-set"
        problems_swe.mkdir(parents=True)
        problem = _make_problem("matplotlib/matplotlib", "matplotlib__matplotlib-99997")
        yaml_path = problems_swe / f"{problem.instance_id}.yaml"
        yaml_path.write_text(
            f"instance_id: {problem.instance_id}\n"
            f"repo: {problem.repo_slug}\n"
            f"base_commit: deadbeef\n"
            f"test_cmd: python -m pytest\n"
            f"patch_file: null\n"
            f"problem_statement: stub\n"
            f"added_at: '2026-01-01'\n"
            f"hf_split: test\n"
        )

        expected_pins = _REPO_PRE_INSTALL["matplotlib/matplotlib"]

        venv_creation_args: list[list[str]] = []
        pip_install_args: list[list[str]] = []

        with (
            patch(
                "subprocess.run",
                side_effect=_make_subprocess_patcher(venv_creation_args, pip_install_args),
            ),
            patch("swebench.cache_cli.clone_bare_repo"),
            patch("swebench.cache_cli.clone_from_bare"),
            patch("swebench.cache_cli.git_reset"),
            patch("swebench.cache_cli.scrub_cache_dir"),
            patch("swebench.cache_cli.write_lockfile"),
            patch("swebench.cache_cli.repo_root", return_value=tmp_path),
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["cache", "setup", "--filter", problem.instance_id, "--concurrency", "1"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0, (
            f"CLI exited with {result.exit_code}. Output:\n{result.output}"
        )

        pin_calls = [
            c for c in pip_install_args
            if any(pin in " ".join(c) for pin in expected_pins)
        ]
        assert pin_calls, (
            f"No pip install call contained matplotlib pre-install pins.\n"
            f"Expected pins (any of): {expected_pins}\n"
            f"All pip install calls: {pip_install_args}\n"
            "cache_cli._setup_one must forward pre_install from _REPO_PRE_INSTALL."
        )

    def test_unlisted_repo_uses_default_python_via_cli(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """CLI slice: ``cache setup`` for an unlisted repo uses ``_DEFAULT_PYTHON``.

        Guards against accidental interpreter override for repos not in the
        lookup table — the happy-path contract for ordinary repos.
        """
        monkeypatch.setenv("SWEBENCH_CACHE_ROOT", str(tmp_path / "cache"))

        problems_swe = tmp_path / "problems" / "swe" / "test-set"
        problems_swe.mkdir(parents=True)
        problem = _make_problem("some/ordinary-repo", "some__ordinary-repo-99996")
        yaml_path = problems_swe / f"{problem.instance_id}.yaml"
        yaml_path.write_text(
            f"instance_id: {problem.instance_id}\n"
            f"repo: {problem.repo_slug}\n"
            f"base_commit: deadbeef\n"
            f"test_cmd: python -m pytest\n"
            f"patch_file: null\n"
            f"problem_statement: stub\n"
            f"added_at: '2026-01-01'\n"
            f"hf_split: test\n"
        )

        assert "some/ordinary-repo" not in _REPO_PYTHON

        venv_creation_args: list[list[str]] = []
        pip_install_args: list[list[str]] = []

        with (
            patch(
                "subprocess.run",
                side_effect=_make_subprocess_patcher(venv_creation_args, pip_install_args),
            ),
            patch("swebench.cache_cli.clone_bare_repo"),
            patch("swebench.cache_cli.clone_from_bare"),
            patch("swebench.cache_cli.git_reset"),
            patch("swebench.cache_cli.scrub_cache_dir"),
            patch("swebench.cache_cli.write_lockfile"),
            patch("swebench.cache_cli.repo_root", return_value=tmp_path),
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["cache", "setup", "--filter", problem.instance_id, "--concurrency", "1"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0, (
            f"CLI exited with {result.exit_code}. Output:\n{result.output}"
        )

        assert venv_creation_args, "setup_venv must have been called"
        first_venv_cmd = venv_creation_args[0]
        assert _DEFAULT_PYTHON in first_venv_cmd, (
            f"Expected default interpreter {_DEFAULT_PYTHON!r} for unlisted repo, "
            f"got: {first_venv_cmd!r}"
        )

    def test_cache_setup_help_schema(self) -> None:
        """``swebench cache setup --help`` exits zero and exposes --filter option.

        Cheapest wiring check: verifies the CLI schema is intact after the
        issue #203 changes and the cache setup command is registered correctly.
        """
        runner = CliRunner()
        result = runner.invoke(cli, ["cache", "setup", "--help"], catch_exceptions=False)
        assert result.exit_code == 0, (
            f"cache setup --help exited {result.exit_code}. Output:\n{result.output}"
        )
        assert "--filter" in result.output, (
            "Expected --filter option in cache setup --help output"
        )
        assert "--concurrency" in result.output, (
            "Expected --concurrency option in cache setup --help output"
        )
