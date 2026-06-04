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
    _resolve_first_existing,
    _UNSAFE_PRE_INSTALL_RE,
    resolve_env_yml_path,
    resolve_requirements_text,
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
        # redirects into root-owned system dirs need root (django py3.5 #311 P2-δ)
        "echo 'en_US UTF-8' > /etc/locale.gen",
        "echo 'deb ...' >> /etc/apt/sources.list",
    ],
)
def test_unsafe_pre_install_matches_system_mutators(cmd: str) -> None:
    assert _UNSAFE_PRE_INSTALL_RE.match(cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        "sed -i 's/requires = \\[\"setuptools\",/requires = \\[\"setuptools==68.0.0\",/' pyproject.toml",
        "echo 'x' > local_config.txt",          # redirect to a repo-relative file: safe
        "python setup.py build > /dev/null",     # /dev is not a root-owned config dir
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


# ---------------------------------------------------------------------------
# requirements.txt / environment.yml sentinel resolution (#311 P2-δ)
# ---------------------------------------------------------------------------

def test_resolve_first_existing(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "found.txt").write_text("x")
    assert _resolve_first_existing(str(tmp_path), ["missing.txt", "a/found.txt"]) == (
        "a/found.txt", str(tmp_path / "a" / "found.txt"),
    )
    assert _resolve_first_existing(str(tmp_path), ["nope.txt"]) is None


def test_resolve_requirements_text_resolves_map_path_inlines_and_cleans(
    tmp_path: Path, monkeypatch
) -> None:
    # flask's real layout: the "requirements.txt" sentinel resolves to
    # requirements/dev.txt, which `-r`-includes requirements/tests.txt.
    monkeypatch.setattr(harness.specs, "reqs_paths",
                        lambda repo: ["requirements/dev.txt"])
    monkeypatch.setattr(harness.specs, "replace_req_packages",
                        lambda: [("types-pkg_resources", "types-setuptools")])
    reqdir = tmp_path / "requirements"
    reqdir.mkdir()
    (reqdir / "dev.txt").write_text(
        "-r tests.txt\n"
        "-e .\n"                       # editable self-install: excluded
        "# a comment\n"                # comment: excluded
        ".[test]\n"                    # extras ref: excluded
        "flask==2.3.0\n"
        "types-pkg_resources==0.1.3\n"  # yanked → replaced (version dropped)
    )
    (reqdir / "tests.txt").write_text("-e .\npytest==7.3.0\n")  # -e . excluded here too

    text = resolve_requirements_text(str(tmp_path), "pallets/flask")
    lines = [l for l in text.split("\n") if l.strip()]
    assert "pytest==7.3.0" in lines           # inlined from the -r include
    assert "flask==2.3.0" in lines
    assert "types-setuptools" in lines        # replacement applied
    assert not any(l.startswith("-e .") for l in lines)
    assert not any(l.startswith("#") for l in lines)
    assert not any("pkg_resources" in l for l in lines)
    assert not any(l.startswith(".[test") for l in lines)


def test_resolve_requirements_text_none_when_no_candidate(tmp_path: Path, monkeypatch) -> None:
    # Repo not in the vendored map → no candidates → None (caller falls back).
    monkeypatch.setattr(harness.specs, "reqs_paths", lambda repo: [])
    assert resolve_requirements_text(str(tmp_path), "unknown/repo") is None
    # In-map path but file absent → still None.
    monkeypatch.setattr(harness.specs, "reqs_paths", lambda repo: ["requirements/dev.txt"])
    assert resolve_requirements_text(str(tmp_path), "pallets/flask") is None


def test_resolve_env_yml_path_prefers_map_order_then_literal(tmp_path: Path, monkeypatch) -> None:
    # xarray-style: first map candidate is ci/requirements/environment.yml.
    monkeypatch.setattr(harness.specs, "env_yml_paths",
                        lambda repo: ["ci/requirements/environment.yml", "environment.yml"])
    deep = tmp_path / "ci" / "requirements"
    deep.mkdir(parents=True)
    (deep / "environment.yml").write_text("name: x\n")
    got = resolve_env_yml_path(str(tmp_path), "pydata/xarray", {"packages": "environment.yml"})
    assert got == str(deep / "environment.yml")

    # No map entry → fall back to the literal packages filename at repo root.
    monkeypatch.setattr(harness.specs, "env_yml_paths", lambda repo: [])
    (tmp_path / "environment.yml").write_text("name: y\n")
    got2 = resolve_env_yml_path(str(tmp_path), "some/repo", {"packages": "environment.yml"})
    assert got2 == str(tmp_path / "environment.yml")


def test_vendored_reqs_paths_match_known_repos() -> None:
    # Guard the vendored data against silent drift on regeneration.
    from swebench import specs
    assert specs.reqs_paths("pallets/flask") == ["requirements/dev.txt"]
    assert specs.reqs_paths("django/django") == ["tests/requirements/py3.txt"]
    assert specs.env_yml_paths("pydata/xarray")[0] == "ci/requirements/environment.yml"
    assert specs.reqs_paths("psf/requests") == []   # inline repo, not in the map
    assert ("types-pkg_resources", "types-setuptools") in specs.replace_req_packages()
