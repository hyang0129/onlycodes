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
    _INSTANCE_POST_INSTALL,
    _INSTANCE_PRE_INSTALL,
    _INSTANCE_PYTHON,
    _N_BUILD_JOBS,
    _REPO_PRE_BUILD,
    _REPO_PRE_INSTALL,
    _REPO_PYTHON,
    _read_sentinel,
    _smoke_import,
    _venv_kwargs,
    _venv_sentinel,
    setup_venv,
)
from swebench.models import Problem


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
    assert any("pybind11" in p for p in pins)


def test_default_python_is_311() -> None:
    assert _DEFAULT_PYTHON == "python3.11"


def test_unlisted_repo_uses_default() -> None:
    """A repo not in _REPO_PYTHON should fall back to _DEFAULT_PYTHON."""
    assert _REPO_PYTHON.get("some/other-repo", _DEFAULT_PYTHON) == _DEFAULT_PYTHON


# ---------------------------------------------------------------------------
# Tests 10–17: instance-level overrides + smoke-import (issue #204)
# ---------------------------------------------------------------------------


def _make_problem(instance_id: str, repo_slug: str) -> Problem:
    """Build a minimal Problem for testing _venv_kwargs lookup."""
    return Problem(
        instance_id=instance_id,
        repo_slug=repo_slug,
        base_commit="abc123",
        test_cmd="pytest",
        problem_statement="test",
        patch_file=None,
        added_at="",
        hf_split="test",
    )


def test_instance_pre_install_override_precedence() -> None:
    """Test 10: instance-level pre_install takes precedence over repo-level."""
    import swebench.harness as h

    problem = _make_problem("foo__bar-1", "foo/bar")
    with patch.dict(h._INSTANCE_PRE_INSTALL, {"foo__bar-1": ["x"]}), \
         patch.dict(h._REPO_PRE_INSTALL, {"foo/bar": ["y"]}):
        from swebench.harness import _venv_kwargs
        result = _venv_kwargs(problem)
        assert result["pre_install"] == ["x"], (
            f"Expected instance-level pin ['x'], got {result['pre_install']!r}"
        )


def test_instance_pre_install_falls_through_when_absent() -> None:
    """Test 11: absent instance entry falls through to repo-level pre_install."""
    import swebench.harness as h

    problem = _make_problem("foo__bar-2", "foo/bar")
    # Ensure no instance entry exists for this id.
    patched_instance = {k: v for k, v in h._INSTANCE_PRE_INSTALL.items() if k != "foo__bar-2"}
    with patch.dict(h._INSTANCE_PRE_INSTALL, patched_instance, clear=True), \
         patch.dict(h._REPO_PRE_INSTALL, {"foo/bar": ["y"]}):
        from swebench.harness import _venv_kwargs
        result = _venv_kwargs(problem)
        assert result["pre_install"] == ["y"], (
            f"Expected repo-level pin ['y'], got {result['pre_install']!r}"
        )


def test_instance_can_suppress_repo_pin() -> None:
    """Test 12: instance entry of [] suppresses the repo-level pin (distinct from absent key)."""
    import swebench.harness as h

    problem = _make_problem("foo__bar-3", "foo/bar")
    with patch.dict(h._INSTANCE_PRE_INSTALL, {"foo__bar-3": []}, clear=False), \
         patch.dict(h._REPO_PRE_INSTALL, {"foo/bar": ["y"]}):
        from swebench.harness import _venv_kwargs
        result = _venv_kwargs(problem)
        assert result["pre_install"] == [], (
            f"Expected [] to suppress repo pin, got {result['pre_install']!r}"
        )


def test_instance_python_override_precedence() -> None:
    """Test 13: instance-level python_bin takes precedence over repo-level."""
    import swebench.harness as h

    problem = _make_problem("foo__bar-4", "foo/bar")
    with patch.dict(h._INSTANCE_PYTHON, {"foo__bar-4": "python3.9"}), \
         patch.dict(h._REPO_PYTHON, {"foo/bar": "python3.10"}):
        from swebench.harness import _venv_kwargs
        result = _venv_kwargs(problem)
        assert result["python_bin"] == "python3.9", (
            f"Expected 'python3.9', got {result['python_bin']!r}"
        )


def test_astropy_6938_uses_python39() -> None:
    """Test 14: astropy__astropy-6938 is configured to use Python 3.9."""
    assert _INSTANCE_PYTHON.get("astropy__astropy-6938") == "python3.9", (
        "astropy__astropy-6938 must use python3.9 (collections.MutableSequence removed in 3.10+)"
    )


def test_sphinx_types_union_instances_use_python39() -> None:
    """sphinx 4.0.x era: instances whose tests transitively import
    ``sphinx/util/typing.py`` must run on Python 3.9.

    The base commits for these two instances ship a typo in typing.py:
    ``if sys.version_info > (3, 10): from types import Union as types_Union``.
    ``types.Union`` does not exist on any released Python. The guard fires on
    Python 3.10.x too (``(3, 10, x) > (3, 10)`` is True by tuple length), so
    pinning anything above 3.9 still hits the broken import.
    """
    for instance_id in ("sphinx-doc__sphinx-9230", "sphinx-doc__sphinx-9281"):
        assert _INSTANCE_PYTHON.get(instance_id) == "python3.9", (
            f"{instance_id} must use python3.9 to skip the broken "
            "`from types import Union` branch in sphinx/util/typing.py"
        )


def test_astropy_5x_pre_install_pins() -> None:
    """Test 15: astropy 5.x instances have the required pre-install pins."""
    for instance_id in ("astropy__astropy-12962", "astropy__astropy-13842"):
        pins = _INSTANCE_PRE_INSTALL.get(instance_id)
        assert pins is not None, f"No instance pins for {instance_id}"
        assert any("setuptools<69" in p for p in pins), f"Missing setuptools<69 in {instance_id}"
        assert any("numpy<2" in p for p in pins), f"Missing numpy<2 in {instance_id}"
        assert any("cython<3" in p for p in pins), f"Missing cython<3 in {instance_id}"
        assert any("extension-helpers" in p for p in pins), f"Missing extension-helpers in {instance_id}"


def test_matplotlib_26160_instance_pins() -> None:
    """Test 18: matplotlib-26160 uses instance-level pins that drop setuptools<65."""
    pins = _INSTANCE_PRE_INSTALL.get("matplotlib__matplotlib-26160")
    assert pins is not None, "No instance pins for matplotlib__matplotlib-26160"
    assert any("pybind11" in p for p in pins), "Missing pybind11"
    assert any("certifi" in p for p in pins), "Missing certifi"
    assert any("wheel" in p for p in pins), "Missing wheel"
    # Must NOT carry the repo-level setuptools<65 (too old for this 2023 build)
    assert not any("setuptools" in p for p in pins), (
        "matplotlib__matplotlib-26160 should not pin setuptools"
    )


def test_matplotlib_35_36_era_setuptools_scm_pin() -> None:
    """Test 19: matplotlib 3.5–3.6 era instances pin setuptools_scm<7.

    setuptools_scm 10.x (the resolved version when unpinned) emits a
    DeprecationWarning ("Version scheme 'release-branch-semver' has been
    renamed") when mpl.__version__ is computed via setuptools_scm.get_version()
    at runtime.  Pytest's filterwarnings=error in matplotlib's conftest promotes
    this to a hard failure before the agent code under test runs.

    The pin must appear in BOTH pre- and post-install lists: pre-install so the
    build sees the right version, post-install because ``pip install -e .``
    pulls setuptools_scm as a runtime dep and would otherwise upgrade it back.
    """
    for instance_id in (
        "matplotlib__matplotlib-23476",
        "matplotlib__matplotlib-24637",
        "matplotlib__matplotlib-25126",
    ):
        pre = _INSTANCE_PRE_INSTALL.get(instance_id)
        assert pre is not None, f"No pre-install pins for {instance_id}"
        assert any("setuptools_scm<7" in p for p in pre), (
            f"Missing setuptools_scm<7 in pre-install for {instance_id}"
        )
        # Must still carry the repo-level pre-build pins
        assert any("setuptools<65" in p for p in pre), (
            f"Missing setuptools<65 in {instance_id}"
        )
        assert any("numpy<2" in p for p in pre), f"Missing numpy<2 in {instance_id}"
        assert any("pyparsing<3" in p for p in pre), (
            f"Missing pyparsing<3 in {instance_id}"
        )
        post = _INSTANCE_POST_INSTALL.get(instance_id)
        assert post is not None, f"No post-install pins for {instance_id}"
        assert any("setuptools_scm<7" in p for p in post), (
            f"Missing setuptools_scm<7 in post-install for {instance_id} "
            f"(pre-install pin is overridden by pip install -e .)"
        )


@pytest.mark.integration
def test_smoke_import_raises_on_broken_venv(tmp_path: Path) -> None:
    """Test 16: _smoke_import raises RuntimeError when the module cannot be imported."""
    import subprocess as sp

    venv_dir = str(tmp_path / "venv")
    # Create a minimal venv (real subprocess — this is an integration test).
    sp.run(["python3.11", "-m", "venv", venv_dir], check=True)
    # matplotlib is NOT installed — import will fail.
    with pytest.raises(RuntimeError, match="matplotlib"):
        _smoke_import(venv_dir, "matplotlib/matplotlib")


def test_smoke_import_skips_unknown_repo(tmp_path: Path) -> None:
    """Test 17: _smoke_import returns silently for unknown repo slugs."""
    # No real venv needed — the function should return before trying to run python.
    venv_dir = str(tmp_path / "no-venv-needed")
    # Should not raise even though the venv doesn't exist.
    _smoke_import(venv_dir, "unknown/repo")  # must not raise


# ---------------------------------------------------------------------------
# Tests for parallel pre-build (issue: sklearn-24677 / sklearn-25694 timeout)
# ---------------------------------------------------------------------------


def test_sklearn_has_pre_build_command() -> None:
    """scikit-learn must have a parallel pre-build command configured."""
    cmd = _REPO_PRE_BUILD.get("scikit-learn/scikit-learn")
    assert cmd is not None, "No pre-build command for scikit-learn/scikit-learn"
    assert "setup.py" in cmd, "Pre-build must invoke setup.py"
    assert "build_ext" in cmd, "Pre-build must call build_ext"
    assert "--inplace" in cmd, "Pre-build must use --inplace"
    assert any(tok.startswith("-j") for tok in cmd), "Pre-build must pass -j N for parallel build"


def test_pre_build_job_count_is_bounded() -> None:
    """_N_BUILD_JOBS must be between 1 and 4 (capped to avoid OOM on large C files)."""
    import os as _os
    assert _N_BUILD_JOBS >= 1
    assert _N_BUILD_JOBS <= 4
    assert _N_BUILD_JOBS == min(4, max(1, _os.cpu_count() or 1))


def test_venv_kwargs_includes_pre_build_cmd_for_sklearn() -> None:
    """_venv_kwargs for scikit-learn must include pre_build_cmd."""
    problem = _make_problem(
        instance_id="scikit-learn__scikit-learn-24677",
        repo_slug="scikit-learn/scikit-learn",
    )
    result = _venv_kwargs(problem)
    assert "pre_build_cmd" in result, "_venv_kwargs must return pre_build_cmd key"
    assert result["pre_build_cmd"] is not None, (
        "pre_build_cmd must be set for scikit-learn/scikit-learn"
    )
    assert "build_ext" in result["pre_build_cmd"]


def test_venv_kwargs_pre_build_cmd_none_for_unknown_repo() -> None:
    """_venv_kwargs for an unknown repo must have pre_build_cmd=None."""
    problem = _make_problem(instance_id="some__other-1", repo_slug="some/other")
    result = _venv_kwargs(problem)
    assert result.get("pre_build_cmd") is None, (
        f"Unknown repo must have pre_build_cmd=None, got {result.get('pre_build_cmd')!r}"
    )


def test_setup_venv_runs_pre_build_cmd_before_editable_install(tmp_path: Path) -> None:
    """setup_venv must invoke pre_build_cmd between pre_install and pip install -e."""
    venv_dir = str(tmp_path / "venv")
    repo_dir = str(tmp_path / "repo")
    os.makedirs(repo_dir)

    call_log: list[str] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
        if "-m" in cmd and "venv" in cmd:
            pip_dir = os.path.join(venv_dir, "bin")
            os.makedirs(pip_dir, exist_ok=True)
            for name in ("pip", "python"):
                Path(os.path.join(pip_dir, name)).touch()
        label = " ".join(str(t) for t in cmd)
        call_log.append(label)
        return _make_success(cmd)

    pre_build = ["python", "setup.py", "build_ext", "--inplace", "-j8"]
    with patch("subprocess.run", side_effect=fake_run):
        setup_venv(
            venv_dir,
            repo_dir,
            python_bin="python3.11",
            pre_install=["cython<3"],
            pre_build_cmd=pre_build,
        )

    # Verify pre-build ran
    pre_build_calls = [c for c in call_log if "build_ext" in c]
    assert pre_build_calls, "Pre-build command was not invoked"

    # Verify ordering: pre-build before editable install
    editable_calls = [c for c in call_log if "-e" in c and repo_dir in c]
    assert editable_calls, "No editable install call found"
    pre_build_idx = next(i for i, c in enumerate(call_log) if "build_ext" in c)
    editable_idx = next(i for i, c in enumerate(call_log) if "-e" in c and repo_dir in c)
    assert pre_build_idx < editable_idx, (
        f"Pre-build (idx={pre_build_idx}) must run before editable install (idx={editable_idx})"
    )


def test_setup_venv_skips_pre_build_cmd_when_none(tmp_path: Path) -> None:
    """setup_venv must not invoke any build_ext when pre_build_cmd is None."""
    venv_dir = str(tmp_path / "venv")
    repo_dir = str(tmp_path / "repo")
    os.makedirs(repo_dir)

    call_log: list[str] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
        if "-m" in cmd and "venv" in cmd:
            pip_dir = os.path.join(venv_dir, "bin")
            os.makedirs(pip_dir, exist_ok=True)
            Path(os.path.join(pip_dir, "pip")).touch()
        call_log.append(" ".join(str(t) for t in cmd))
        return _make_success(cmd)

    with patch("subprocess.run", side_effect=fake_run):
        setup_venv(venv_dir, repo_dir, python_bin="python3.11", pre_install=["cython<3"])

    assert not any("build_ext" in c for c in call_log), (
        f"build_ext should not be called when pre_build_cmd=None; calls: {call_log}"
    )
