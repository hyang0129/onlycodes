"""Unit tests for the official-spec build path (#311):
``swebench/specs.py`` + ``harness._venv_kwargs`` precedence + version round-trip.

Hermetic: exercises the vendored ``swebench/data/official_specs.json`` and the
pure lookup/translation helpers. No venv builds, no network.
"""

from __future__ import annotations

from pathlib import Path

from swebench import specs
from swebench.harness import (
    _DEFAULT_PYTHON,
    _INSTANCE_PYTHON,
    _REPO_PYTHON,
    _venv_kwargs,
)
from swebench.models import Problem


# --------------------------------------------------------------------------
# specs.pip_requirements / python_bin / spec_for
# --------------------------------------------------------------------------

def test_pip_requirements_passthrough_and_translation() -> None:
    spec = {
        "pip_packages": ["numpy==1.19.2", "cython"],
        "packages": "scipy pytest 'pandas<2.0.0'",
    }
    reqs = specs.pip_requirements(spec)
    assert reqs == ["numpy==1.19.2", "cython", "scipy", "pytest", "pandas<2.0.0"]


def test_pip_requirements_conda_equals_becomes_pip_pin() -> None:
    # conda single '=' -> pip '=='
    assert specs.pip_requirements({"packages": "setuptools=38.2.4"}) == ["setuptools==38.2.4"]


def test_pip_requirements_skips_file_refs() -> None:
    # requirements.txt / environment.yml are deferred (PR-1 scope), not pip pins.
    assert specs.pip_requirements({"packages": "requirements.txt"}) == []
    assert specs.pip_requirements({"packages": "environment.yml pytest"}) == ["pytest"]


def test_pip_requirements_dedup_preserves_order() -> None:
    spec = {"pip_packages": ["pytest", "numpy"], "packages": "pytest scipy"}
    assert specs.pip_requirements(spec) == ["pytest", "numpy", "scipy"]


def test_python_bin() -> None:
    assert specs.python_bin({"python": "3.9"}) == "python3.9"
    assert specs.python_bin({}) is None


def test_spec_for_requires_version() -> None:
    assert specs.spec_for("psf/requests", None) is None
    # A repo present in the vendored map resolves for a known version.
    reqs = specs._load().get("psf/requests", {})
    assert reqs, "vendored map should contain psf/requests"
    some_version = next(iter(reqs))
    assert specs.spec_for("psf/requests", some_version) is not None


def test_vendored_map_nonempty() -> None:
    m = specs._load()
    assert len(m) >= 10
    assert "django/django" in m and "astropy/astropy" in m


# --------------------------------------------------------------------------
# harness._venv_kwargs precedence: hand-tables > official-spec > default
# --------------------------------------------------------------------------

def _problem(instance_id: str, repo: str, version: str | None) -> Problem:
    return Problem(
        instance_id=instance_id, repo_slug=repo, base_commit="x",
        test_cmd="python -m pytest", problem_statement="", patch_file=None,
        added_at="", hf_split="test", version=version,
    )


def test_venv_kwargs_uses_official_spec_when_no_hand_entry() -> None:
    # Pick a (repo, version) in the vendored map whose instance isn't hand-tabled.
    requests_versions = specs._load()["psf/requests"]
    ver, spec = next(
        (v, s) for v, s in requests_versions.items() if s.get("python")
    )
    p = _problem("psf__requests-99999", "psf/requests", ver)
    assert p.instance_id not in _INSTANCE_PYTHON
    assert "psf/requests" not in _REPO_PYTHON
    kw = _venv_kwargs(p)
    assert kw["python_bin"] == f"python{spec['python']}"
    # spec pins flow into pre_install
    if specs.pip_requirements(spec):
        assert kw["pre_install"] == specs.pip_requirements(spec)


def test_venv_kwargs_default_when_no_version() -> None:
    p = _problem("psf__requests-99999", "psf/requests", None)
    kw = _venv_kwargs(p)
    assert kw["python_bin"] == _DEFAULT_PYTHON
    assert kw["pre_install"] is None


def test_venv_kwargs_repo_table_overrides_spec() -> None:
    # scikit-learn has a repo-level python pin that must win over the spec's 3.6.
    assert _REPO_PYTHON.get("scikit-learn/scikit-learn") is not None
    sk_versions = specs._load()["scikit-learn/scikit-learn"]
    ver = next(iter(sk_versions))
    p = _problem("scikit-learn__scikit-learn-99999", "scikit-learn/scikit-learn", ver)
    kw = _venv_kwargs(p)
    assert kw["python_bin"] == _REPO_PYTHON["scikit-learn/scikit-learn"]


# --------------------------------------------------------------------------
# Problem version round-trips through YAML
# --------------------------------------------------------------------------

def test_problem_version_roundtrip(tmp_path: Path) -> None:
    p = _problem("django__django-1", "django/django", "2.2")
    p.environment_setup_commit = "deadbeef"
    out = tmp_path / "x.yaml"
    p.to_yaml(out)
    loaded = Problem.from_yaml(out)
    assert loaded.version == "2.2"
    assert loaded.environment_setup_commit == "deadbeef"


def test_problem_missing_version_loads_as_none(tmp_path: Path) -> None:
    # A legacy YAML without version/environment_setup_commit still loads.
    out = tmp_path / "legacy.yaml"
    out.write_text(
        "instance_id: a__a-1\nrepo: a/a\nbase_commit: x\ntest_cmd: pytest\n"
        "problem_statement: ''\npatch_file: null\nadded_at: ''\nhf_split: test\n"
    )
    loaded = Problem.from_yaml(out)
    assert loaded.version is None and loaded.environment_setup_commit is None
