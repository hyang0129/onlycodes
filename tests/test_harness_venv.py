"""Tests for the per-repo Python-version sentinel in setup_venv().

Covers the three paths introduced by issue #203:
  (a) sentinel is written on fresh venv creation,
  (b) a mismatched sentinel forces a full venv rebuild,
  (c) a matching sentinel takes the existing-venv reuse path.

All subprocess.run calls are monkeypatched so no real venvs are created.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from swebench.harness import (
    _DEFAULT_PYTHON,
    _REPO_PRE_INSTALL,
    _REPO_PYTHON,
    _read_sentinel,
    _venv_sentinel,
    setup_venv,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_success(args: list[str] | None = None) -> MagicMock:
    """Return a MagicMock that looks like a successful subprocess.CompletedProcess."""
    m = MagicMock()
    m.returncode = 0
    m.args = args or []
    m.stdout = ""
    m.stderr = ""
    return m


# ---------------------------------------------------------------------------
# Sentinel unit tests
# ---------------------------------------------------------------------------


def test_sentinel_written_after_fresh_venv_creation(tmp_path: Path) -> None:
    """Sentinel file is written with the python_bin after a successful fresh install."""
    venv_dir = str(tmp_path / "venv")
    repo_dir = str(tmp_path / "repo")
    os.makedirs(repo_dir)

    calls_made: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
        calls_made.append(cmd)
        # After the venv creation call, create bin/pip so the sentinel write can
        # happen (the real code checks os.path.isdir(venv_dir) first).
        if len(cmd) >= 3 and "-m" in cmd and "venv" in cmd:
            pip_dir = os.path.join(venv_dir, "bin")
            os.makedirs(pip_dir, exist_ok=True)
            Path(os.path.join(pip_dir, "pip")).touch()
        return _make_success(cmd)

    with patch("subprocess.run", side_effect=fake_run):
        setup_venv(venv_dir, repo_dir, python_bin="python3.10")

    sentinel_value = _read_sentinel(venv_dir)
    assert sentinel_value == "python3.10", (
        f"Expected sentinel 'python3.10', got {sentinel_value!r}"
    )


def test_sentinel_mismatch_forces_rebuild(tmp_path: Path) -> None:
    """When the sentinel doesn't match python_bin, the old venv is wiped and rebuilt."""
    venv_dir = str(tmp_path / "venv")
    repo_dir = str(tmp_path / "repo")
    os.makedirs(repo_dir)

    # Create a pre-existing venv skeleton with pip and a WRONG sentinel.
    pip_dir = os.path.join(venv_dir, "bin")
    os.makedirs(pip_dir)
    Path(os.path.join(pip_dir, "pip")).touch()
    # Sentinel says python3.11 was used:
    Path(_venv_sentinel(venv_dir)).write_text("python3.11\n")

    venv_creation_calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
        if len(cmd) >= 3 and "-m" in cmd and "venv" in cmd:
            venv_creation_calls.append(cmd)
            # Recreate the bin/pip after wipe so later calls succeed.
            new_pip_dir = os.path.join(venv_dir, "bin")
            os.makedirs(new_pip_dir, exist_ok=True)
            Path(os.path.join(new_pip_dir, "pip")).touch()
        return _make_success(cmd)

    with patch("subprocess.run", side_effect=fake_run):
        setup_venv(venv_dir, repo_dir, python_bin="python3.10")

    # Venv creation must have been called exactly once (the rebuild).
    assert len(venv_creation_calls) == 1, (
        f"Expected 1 venv creation call, got {len(venv_creation_calls)}: "
        f"{venv_creation_calls}"
    )
    # The creation call must use the requested python_bin.
    assert "python3.10" in venv_creation_calls[0], (
        f"venv creation did not use python3.10: {venv_creation_calls[0]}"
    )
    # Sentinel must now reflect the new interpreter.
    assert _read_sentinel(venv_dir) == "python3.10"


def test_matching_sentinel_takes_reuse_path(tmp_path: Path) -> None:
    """When the sentinel matches python_bin, setup_venv() reuses the existing venv."""
    venv_dir = str(tmp_path / "venv")
    repo_dir = str(tmp_path / "repo")
    os.makedirs(repo_dir)

    # Create a pre-existing venv with pip and a MATCHING sentinel.
    pip_dir = os.path.join(venv_dir, "bin")
    os.makedirs(pip_dir)
    pip_path = os.path.join(pip_dir, "pip")
    Path(pip_path).touch()
    Path(_venv_sentinel(venv_dir)).write_text("python3.11\n")

    venv_creation_calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
        if len(cmd) >= 3 and "-m" in cmd and "venv" in cmd:
            venv_creation_calls.append(cmd)
        return _make_success(cmd)

    with patch("subprocess.run", side_effect=fake_run):
        setup_venv(venv_dir, repo_dir, python_bin="python3.11")

    # Venv must NOT have been recreated.
    assert venv_creation_calls == [], (
        f"Unexpected venv creation on reuse path: {venv_creation_calls}"
    )


def test_missing_pip_triggers_rebuild_regardless_of_sentinel(tmp_path: Path) -> None:
    """A venv directory with a sentinel but no pip is treated as broken and rebuilt."""
    venv_dir = str(tmp_path / "venv")
    repo_dir = str(tmp_path / "repo")
    os.makedirs(repo_dir)

    # Create the venv dir and sentinel but no bin/pip.
    os.makedirs(venv_dir)
    Path(_venv_sentinel(venv_dir)).write_text("python3.11\n")
    # Do NOT create bin/pip.

    venv_creation_calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
        if len(cmd) >= 3 and "-m" in cmd and "venv" in cmd:
            venv_creation_calls.append(cmd)
            new_pip_dir = os.path.join(venv_dir, "bin")
            os.makedirs(new_pip_dir, exist_ok=True)
            Path(os.path.join(new_pip_dir, "pip")).touch()
        return _make_success(cmd)

    with patch("subprocess.run", side_effect=fake_run):
        setup_venv(venv_dir, repo_dir, python_bin="python3.11")

    assert len(venv_creation_calls) == 1, (
        f"Expected rebuild when pip is missing, got {len(venv_creation_calls)} creation calls"
    )


def test_pre_install_uses_no_build_isolation(tmp_path: Path) -> None:
    """When pre_install is non-empty, the editable install uses --no-build-isolation."""
    venv_dir = str(tmp_path / "venv")
    repo_dir = str(tmp_path / "repo")
    os.makedirs(repo_dir)

    install_calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
        if "-m" in cmd and "venv" in cmd:
            pip_dir = os.path.join(venv_dir, "bin")
            os.makedirs(pip_dir, exist_ok=True)
            Path(os.path.join(pip_dir, "pip")).touch()
        if "install" in cmd:
            install_calls.append(cmd)
        return _make_success(cmd)

    with patch("subprocess.run", side_effect=fake_run):
        setup_venv(
            venv_dir,
            repo_dir,
            python_bin="python3.11",
            pre_install=["setuptools<60", "numpy<1.24"],
        )

    # Find the editable install call.
    editable_calls = [c for c in install_calls if "-e" in c and repo_dir in c]
    assert editable_calls, "No editable install call found"
    assert any("--no-build-isolation" in c for c in editable_calls), (
        f"--no-build-isolation not found in any editable install call: {editable_calls}"
    )


def test_no_build_isolation_absent_without_pre_install(tmp_path: Path) -> None:
    """Without pre_install, the editable install does NOT use --no-build-isolation."""
    venv_dir = str(tmp_path / "venv")
    repo_dir = str(tmp_path / "repo")
    os.makedirs(repo_dir)

    install_calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
        if "-m" in cmd and "venv" in cmd:
            pip_dir = os.path.join(venv_dir, "bin")
            os.makedirs(pip_dir, exist_ok=True)
            Path(os.path.join(pip_dir, "pip")).touch()
        if "install" in cmd:
            install_calls.append(cmd)
        return _make_success(cmd)

    with patch("subprocess.run", side_effect=fake_run):
        setup_venv(venv_dir, repo_dir, python_bin="python3.11")

    editable_calls = [c for c in install_calls if "-e" in c and repo_dir in c]
    assert editable_calls, "No editable install call found"
    for c in editable_calls:
        assert "--no-build-isolation" not in c, (
            f"--no-build-isolation found unexpectedly without pre_install: {c}"
        )


# ---------------------------------------------------------------------------
# Lookup table sanity checks
# ---------------------------------------------------------------------------


def test_sklearn_uses_python310() -> None:
    assert _REPO_PYTHON.get("scikit-learn/scikit-learn") == "python3.10"


def test_sklearn_pre_install_pins() -> None:
    pins = _REPO_PRE_INSTALL.get("scikit-learn/scikit-learn")
    assert pins is not None
    assert any("setuptools<60" in p for p in pins)
    assert any("numpy<1.24" in p for p in pins)
    assert any("cython<3" in p for p in pins)


def test_matplotlib_pre_install_pins() -> None:
    pins = _REPO_PRE_INSTALL.get("matplotlib/matplotlib")
    assert pins is not None
    assert any("numpy<2" in p for p in pins)
    assert any("cython<3" in p for p in pins)
    assert any("setuptools<65" in p for p in pins)


def test_default_python_is_311() -> None:
    assert _DEFAULT_PYTHON == "python3.11"


def test_unlisted_repo_uses_default() -> None:
    """A repo not in _REPO_PYTHON should fall back to _DEFAULT_PYTHON."""
    assert _REPO_PYTHON.get("some/other-repo", _DEFAULT_PYTHON) == _DEFAULT_PYTHON
