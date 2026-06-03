"""Hermetic unit tests for the conda-native env builder (P2-γ, #311).

Exercises the pure helpers, the guard logic, and the error paths of
``harness.setup_conda_env`` without invoking micromamba or the network. The
real end-to-end build is validated separately (manual P2-γ validation).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from swebench import harness
from swebench.harness import (
    CondaBuildError,
    _conda_path_env,
    _find_micromamba,
    _UNSAFE_PRE_INSTALL_RE,
    setup_conda_env,
    setup_venv,
)


def test_find_micromamba_env_override(tmp_path: Path, monkeypatch) -> None:
    fake = tmp_path / "micromamba"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setenv("ONLYCODES_MICROMAMBA", str(fake))
    assert _find_micromamba() == str(fake)


def test_find_micromamba_override_ignored_if_missing(monkeypatch) -> None:
    monkeypatch.setenv("ONLYCODES_MICROMAMBA", "/nonexistent/micromamba")
    # Falls through to PATH / known locations (may be None in CI) — never the bad override.
    assert _find_micromamba() != "/nonexistent/micromamba"


def test_conda_path_env_prepends_bin_and_clears_activation(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("PYTHONHOME", "/leak")
    monkeypatch.setenv("VIRTUAL_ENV", "/leak/venv")
    env = _conda_path_env("/opt/env")
    assert env["PATH"].split(os.pathsep)[0] == "/opt/env/bin"
    assert "PYTHONHOME" not in env
    assert "VIRTUAL_ENV" not in env


@pytest.mark.parametrize(
    "cmd",
    [
        "apt-get update && apt-get install -y locales",
        "sudo apt-get install -y imagemagick",
        "locale-gen en_US.UTF-8",
        "add-apt-repository ppa:foo/bar",
        "  apt install build-essential",
    ],
)
def test_unsafe_pre_install_matches_system_mutators(cmd: str) -> None:
    assert _UNSAFE_PRE_INSTALL_RE.match(cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        "sed -i 's/requires = \\[\"setuptools\",/requires = \\[\"setuptools==68.0.0\",/' pyproject.toml",
        "echo 'en_US UTF-8' > /etc/locale.gen",
        "python -m pip install -e .",
    ],
)
def test_unsafe_pre_install_allows_safe_source_pins(cmd: str) -> None:
    assert not _UNSAFE_PRE_INSTALL_RE.match(cmd)


def test_setup_conda_env_raises_when_micromamba_absent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(harness, "_find_micromamba", lambda: None)
    with pytest.raises(CondaBuildError, match="micromamba not found"):
        setup_conda_env(str(tmp_path / "env"), str(tmp_path), spec={"python": "3.9"})


def test_setup_conda_env_raises_when_spec_has_no_python(tmp_path: Path) -> None:
    # micromamba_bin is provided (exists) so we reach the python check.
    with pytest.raises(CondaBuildError, match="no python"):
        setup_conda_env(str(tmp_path / "env"), str(tmp_path), spec={}, micromamba_bin=sys.executable)


def test_setup_venv_refuses_to_clobber_a_conda_env(tmp_path: Path) -> None:
    # A dir carrying a conda sentinel must not be rebuilt as a venv (would rmtree it).
    env = tmp_path / "venv"
    env.mkdir()
    (env / ".python_bin").write_text("conda:python3.9\n")
    with pytest.raises(CondaBuildError, match="holds a conda env"):
        setup_venv(str(env), str(tmp_path), python_bin="python3.11")
    # The guard must fire BEFORE any deletion.
    assert (env / ".python_bin").exists()
