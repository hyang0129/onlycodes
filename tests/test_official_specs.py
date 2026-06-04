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
# Conda-native build accessors (P2-γ, #311)
# --------------------------------------------------------------------------

def test_conda_python_is_bare_version() -> None:
    assert specs.conda_python({"python": "3.6"}) == "3.6"
    assert specs.conda_python({"python": 3.9}) == "3.9"  # tolerate non-str
    assert specs.conda_python({}) is None


def test_install_command_verbatim() -> None:
    spec = {"install": "python -m pip install -e .[test] --verbose"}
    assert specs.install_command(spec) == "python -m pip install -e .[test] --verbose"
    assert specs.install_command({}) is None
    assert specs.install_command({"install": "   "}) is None


def test_pre_install_commands_filters_blanks_keeps_order() -> None:
    spec = {"pre_install": ["sed -i 's/a/b/' setup.py", "", "  ", "apt-get update"]}
    assert specs.pre_install_commands(spec) == ["sed -i 's/a/b/' setup.py", "apt-get update"]
    assert specs.pre_install_commands({}) == []


def test_pip_packages_cleaned() -> None:
    assert specs.pip_packages({"pip_packages": [" numpy==1.19.2 ", "", "pytest"]}) == [
        "numpy==1.19.2", "pytest",
    ]
    assert specs.pip_packages({}) == []


def test_eval_commands_and_no_use_env() -> None:
    assert specs.eval_commands({"eval_commands": ["echo hi", ""]}) == ["echo hi"]
    assert specs.eval_commands({}) == []
    assert specs.no_use_env({"no_use_env": True}) is True
    assert specs.no_use_env({}) is False


def test_eval_env_parses_exports_and_ignores_system_commands() -> None:
    spec = {
        "eval_commands": [
            "export LANG=en_US.UTF-8",
            "export PYTHONIOENCODING=utf8",
            "  export LC_ALL=en_US.UTF-8  ",          # surrounding whitespace tolerated
            "sed -i 's/x/y/' /etc/locale.gen && locale-gen",  # system-level: not env
            "",                                        # blank dropped
        ]
    }
    assert specs.eval_env(spec) == {
        "LANG": "en_US.UTF-8",
        "PYTHONIOENCODING": "utf8",
        "LC_ALL": "en_US.UTF-8",
    }
    # The non-export command is surfaced separately so the caller can log the skip.
    assert specs.eval_system_commands(spec) == [
        "sed -i 's/x/y/' /etc/locale.gen && locale-gen"
    ]
    assert specs.eval_env({}) == {}
    assert specs.eval_system_commands({}) == []


def test_eval_env_strips_quotes_no_shell_expansion() -> None:
    spec = {"eval_commands": ["export FOO='bar baz'", 'export QUX="q"', "export RAW=$HOME"]}
    env = specs.eval_env(spec)
    assert env["FOO"] == "bar baz"   # single quotes stripped
    assert env["QUX"] == "q"         # double quotes stripped
    assert env["RAW"] == "$HOME"     # left verbatim — no shell expansion


def test_eval_env_real_vendored_django() -> None:
    # Django specs carry the locale pins as export-style eval_commands; they must
    # surface as a plain env dict for the Gate-2 collect (#311 P2-δ test fidelity).
    m = specs._load()
    dj = m["django/django"]["1.10"]
    env = specs.eval_env(dj)
    assert env.get("LANG") == "en_US.UTF-8"
    assert env.get("LC_ALL") == "en_US.UTF-8"
    assert env.get("LANGUAGE") == "en_US:en"
    # Every value parsed is non-empty and quote-free.
    assert all(v and "'" not in v and '"' not in v for v in env.values())


def test_packages_kind_discrimination() -> None:
    assert specs.packages_kind({}) == "none"
    assert specs.packages_kind({"packages": "  "}) == "none"
    assert specs.packages_kind({"packages": "requirements.txt"}) == "requirements_txt"
    assert specs.packages_kind({"packages": "environment.yml"}) == "environment_yml"
    assert specs.packages_kind({"packages": "environment.yaml"}) == "environment_yml"
    assert specs.packages_kind({"packages": "numpy scipy 'pandas<2'"}) == "inline"


def test_packages_file_only_for_file_refs() -> None:
    assert specs.packages_file({"packages": "requirements.txt"}) == "requirements.txt"
    assert specs.packages_file({"packages": "environment.yml"}) == "environment.yml"
    assert specs.packages_file({"packages": "numpy scipy"}) is None
    assert specs.packages_file({}) is None


def test_conda_packages_unquotes_but_does_not_translate() -> None:
    # Quotes stripped; conda single-'=' pins are NOT rewritten to '==' (conda syntax kept).
    spec = {"packages": "'numpy==1.19.2' scipy 'pandas<2.0.0' setuptools=38.2.4"}
    assert specs.conda_packages(spec) == [
        "numpy==1.19.2", "scipy", "pandas<2.0.0", "setuptools=38.2.4",
    ]
    # File-ref / absent → no inline conda packages.
    assert specs.conda_packages({"packages": "requirements.txt"}) == []
    assert specs.conda_packages({}) == []


def test_conda_accessors_against_real_vendored_data() -> None:
    m = specs._load()
    # astropy v5.3: the build-isolation-needing install line PR-1 broke.
    ast = m["astropy/astropy"]["v5.3"]
    assert specs.install_command(ast) == "python -m pip install -e .[test] --verbose"
    assert specs.conda_python(ast) == "3.10"
    # django uses a requirements.txt ref.
    dj = next(iter(m["django/django"].values()))
    assert specs.packages_kind(dj) == "requirements_txt"
    assert specs.packages_file(dj) == "requirements.txt"
    # matplotlib / xarray are the genuine conda-native (environment.yml) cases.
    assert any(
        specs.packages_kind(s) == "environment_yml"
        for s in m["matplotlib/matplotlib"].values()
    )


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
