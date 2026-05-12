"""Component test: cache_cli._setup_one → harness.setup_venv kwargs contract.

Boundary: cache_cli._setup_one() calls harness.setup_venv() at line 113 of
cache_cli.py.  Issue #203 added per-repo Python-version and pre-install-pin
lookup tables (_REPO_PYTHON, _REPO_PRE_INSTALL) to harness.py, and wired them
through run.py via the helper _venv_kwargs().  However, cache_cli._setup_one
still calls setup_venv(venv_dir, repo_dir) without passing those kwargs,
meaning the cache-warm-up path always uses the default python3.11 with no
pre-install pins — even for repos like scikit-learn that require python3.10 and
specific pin overrides.

These component tests verify the *contract* between the two real modules:

  1. When _setup_one is invoked with a Problem whose repo_slug is in
     _REPO_PYTHON, the setup_venv call must receive the correct python_bin.
  2. When the repo_slug is in _REPO_PRE_INSTALL, the correct pre_install pins
     must reach setup_venv.
  3. For an unlisted repo, setup_venv must be called with _DEFAULT_PYTHON and
     no pre_install.

Both real modules cooperate across the boundary.  The only doubles are I/O
seams: filesystem (cache root redirected to tmp_path), subprocess (all
subprocess.run calls patched to no-ops), and the git/network operations
(clone_bare_repo, clone_from_bare, git_reset, scrub_cache_dir, write_lockfile).
setup_venv itself is NOT doubled — we observe what arguments it receives by
intercepting subprocess.run at the lowest layer.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from swebench.cache_cli import _setup_one
from swebench.harness import (
    _DEFAULT_PYTHON,
    _REPO_PRE_INSTALL,
    _REPO_PYTHON,
)
from swebench.models import Problem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_problem(repo_slug: str) -> Problem:
    return Problem(
        instance_id=f"test__{repo_slug.replace('/', '__')}",
        repo_slug=repo_slug,
        base_commit="deadbeef",
        test_cmd="python -m pytest",
        problem_statement="stub",
        patch_file=None,
        added_at="2024-01-01",
        hf_split="test",
    )


def _make_subprocess_ok(*args: Any, **kwargs: Any) -> MagicMock:
    """Return a CompletedProcess-like mock with returncode=0."""
    m = MagicMock()
    m.returncode = 0
    m.stdout = b""
    m.stderr = b""
    return m


# ---------------------------------------------------------------------------
# Component tests
# ---------------------------------------------------------------------------


@pytest.mark.component
class TestCacheCliSetupVenvContract:
    """Verify that _setup_one forwards the correct python_bin and pre_install
    kwargs to harness.setup_venv for each repo category."""

    def test_known_repo_python_version_forwarded(self, tmp_path: Path, monkeypatch: Any) -> None:
        """For scikit-learn, setup_venv must receive python_bin='python3.10'.

        This test crosses the cache_cli → harness boundary without doubling
        setup_venv itself.  It intercepts only subprocess.run (real I/O) and
        the git/network helpers that need network access.
        """
        # Redirect cache root so no real disk cache is written.
        monkeypatch.setenv("SWEBENCH_CACHE_ROOT", str(tmp_path / "cache"))

        problem = _make_problem("scikit-learn/scikit-learn")
        expected_python = _REPO_PYTHON["scikit-learn/scikit-learn"]
        assert expected_python == "python3.10", "Test precondition: sentinel value"

        venv_creation_args: list[list[str]] = []

        def fake_subprocess_run(cmd: Any, **kwargs: Any) -> MagicMock:
            cmd_list = list(cmd) if not isinstance(cmd, str) else cmd.split()
            # Capture any call that creates a venv (python -m venv ...)
            if isinstance(cmd, (list, tuple)) and "-m" in cmd_list and "venv" in cmd_list:
                venv_creation_args.append(cmd_list)
                # Create bin/pip so setup_venv doesn't abort.
                # Find the venv_dir argument (last non-flag arg after 'venv').
                venv_dir_arg = cmd_list[-1]
                pip_bin = os.path.join(venv_dir_arg, "bin", "pip")
                os.makedirs(os.path.dirname(pip_bin), exist_ok=True)
                Path(pip_bin).touch()
            return _make_subprocess_ok(cmd, **kwargs)

        with (
            patch("subprocess.run", side_effect=fake_subprocess_run),
            patch("swebench.cache_cli.clone_bare_repo"),
            patch("swebench.cache_cli.clone_from_bare"),
            patch("swebench.cache_cli.git_reset"),
            patch("swebench.cache_cli.scrub_cache_dir"),
            patch("swebench.cache_cli.write_lockfile"),
        ):
            _id, ok, msg = _setup_one(problem, force=True)

        assert venv_creation_args, (
            "setup_venv never called subprocess to create a venv — "
            "the boundary between cache_cli and harness may have been severed"
        )
        first_venv_cmd = venv_creation_args[0]
        assert expected_python in first_venv_cmd, (
            f"setup_venv venv-creation call used wrong interpreter: {first_venv_cmd!r}. "
            f"Expected {expected_python!r}. "
            "cache_cli._setup_one must forward python_bin from _REPO_PYTHON."
        )

    def test_known_repo_pre_install_pins_forwarded(self, tmp_path: Path, monkeypatch: Any) -> None:
        """For scikit-learn, setup_venv must receive the correct pre_install pins.

        The pins from _REPO_PRE_INSTALL['scikit-learn/scikit-learn'] must appear
        in a pip install call that precedes the editable install, signalling that
        the pre_install kwarg reached setup_venv.
        """
        monkeypatch.setenv("SWEBENCH_CACHE_ROOT", str(tmp_path / "cache"))

        problem = _make_problem("scikit-learn/scikit-learn")
        expected_pins = _REPO_PRE_INSTALL["scikit-learn/scikit-learn"]
        assert "setuptools<60" in expected_pins, "Test precondition: pin table"

        pre_install_calls: list[list[str]] = []

        def fake_subprocess_run(cmd: Any, **kwargs: Any) -> MagicMock:
            cmd_list = list(cmd) if not isinstance(cmd, (str, bytes)) else []
            if isinstance(cmd, (list, tuple)):
                cmd_list = list(cmd)
                # Capture pip install calls (excluding editable installs)
                if "install" in cmd_list and "-e" not in cmd_list:
                    pre_install_calls.append(cmd_list)
                # Create bin/pip when a venv is being created.
                if "-m" in cmd_list and "venv" in cmd_list:
                    venv_dir_arg = cmd_list[-1]
                    pip_bin = os.path.join(venv_dir_arg, "bin", "pip")
                    os.makedirs(os.path.dirname(pip_bin), exist_ok=True)
                    Path(pip_bin).touch()
            return _make_subprocess_ok(cmd, **kwargs)

        with (
            patch("subprocess.run", side_effect=fake_subprocess_run),
            patch("swebench.cache_cli.clone_bare_repo"),
            patch("swebench.cache_cli.clone_from_bare"),
            patch("swebench.cache_cli.git_reset"),
            patch("swebench.cache_cli.scrub_cache_dir"),
            patch("swebench.cache_cli.write_lockfile"),
        ):
            _setup_one(problem, force=True)

        # Find any install call that contains one of the known pins.
        pin_install_calls = [
            c for c in pre_install_calls
            if any(pin in " ".join(c) for pin in expected_pins)
        ]
        assert pin_install_calls, (
            f"No pip install call containing pre_install pins was observed.\n"
            f"Expected pins: {expected_pins}\n"
            f"All non-editable pip install calls seen: {pre_install_calls}\n"
            "cache_cli._setup_one must forward pre_install from _REPO_PRE_INSTALL."
        )

    def test_unlisted_repo_uses_default_python(self, tmp_path: Path, monkeypatch: Any) -> None:
        """For a repo not in _REPO_PYTHON, setup_venv must use _DEFAULT_PYTHON.

        This is the happy-path contract: an ordinary repo must not receive a
        non-default interpreter just because the lookup table was changed.
        """
        monkeypatch.setenv("SWEBENCH_CACHE_ROOT", str(tmp_path / "cache"))

        problem = _make_problem("some/ordinary-repo")
        # Precondition: this slug must not appear in the lookup table.
        assert "some/ordinary-repo" not in _REPO_PYTHON

        venv_creation_args: list[list[str]] = []

        def fake_subprocess_run(cmd: Any, **kwargs: Any) -> MagicMock:
            cmd_list = list(cmd) if isinstance(cmd, (list, tuple)) else []
            if "-m" in cmd_list and "venv" in cmd_list:
                venv_creation_args.append(cmd_list)
                venv_dir_arg = cmd_list[-1]
                pip_bin = os.path.join(venv_dir_arg, "bin", "pip")
                os.makedirs(os.path.dirname(pip_bin), exist_ok=True)
                Path(pip_bin).touch()
            return _make_subprocess_ok(cmd, **kwargs)

        with (
            patch("subprocess.run", side_effect=fake_subprocess_run),
            patch("swebench.cache_cli.clone_bare_repo"),
            patch("swebench.cache_cli.clone_from_bare"),
            patch("swebench.cache_cli.git_reset"),
            patch("swebench.cache_cli.scrub_cache_dir"),
            patch("swebench.cache_cli.write_lockfile"),
        ):
            _setup_one(problem, force=True)

        assert venv_creation_args, "setup_venv must have been called"
        first_venv_cmd = venv_creation_args[0]
        assert _DEFAULT_PYTHON in first_venv_cmd, (
            f"Expected {_DEFAULT_PYTHON!r} in venv creation call for unlisted repo, "
            f"got: {first_venv_cmd!r}"
        )

    def test_unlisted_repo_has_no_pre_install_calls(self, tmp_path: Path, monkeypatch: Any) -> None:
        """For a repo not in _REPO_PRE_INSTALL, no pre-install pins should be injected.

        Guards against accidental pin injection for repos that don't need it.
        """
        monkeypatch.setenv("SWEBENCH_CACHE_ROOT", str(tmp_path / "cache"))

        problem = _make_problem("some/ordinary-repo")
        assert "some/ordinary-repo" not in _REPO_PRE_INSTALL

        pre_install_calls: list[list[str]] = []

        def fake_subprocess_run(cmd: Any, **kwargs: Any) -> MagicMock:
            cmd_list = list(cmd) if isinstance(cmd, (list, tuple)) else []
            if "install" in cmd_list and "-e" not in cmd_list:
                # Exclude the baseline setuptools/wheel/pytest installs
                if not any(
                    x in " ".join(cmd_list)
                    for x in ("setuptools wheel", "setuptools", "wheel", "pytest")
                ):
                    pre_install_calls.append(cmd_list)
            if "-m" in cmd_list and "venv" in cmd_list:
                venv_dir_arg = cmd_list[-1]
                pip_bin = os.path.join(venv_dir_arg, "bin", "pip")
                os.makedirs(os.path.dirname(pip_bin), exist_ok=True)
                Path(pip_bin).touch()
            return _make_subprocess_ok(cmd, **kwargs)

        with (
            patch("subprocess.run", side_effect=fake_subprocess_run),
            patch("swebench.cache_cli.clone_bare_repo"),
            patch("swebench.cache_cli.clone_from_bare"),
            patch("swebench.cache_cli.git_reset"),
            patch("swebench.cache_cli.scrub_cache_dir"),
            patch("swebench.cache_cli.write_lockfile"),
        ):
            _setup_one(problem, force=True)

        assert pre_install_calls == [], (
            f"Unexpected pre-install pip calls for unlisted repo: {pre_install_calls}"
        )
