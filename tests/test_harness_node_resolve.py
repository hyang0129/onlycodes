"""Tests for sympy test-node resolution in ``harness.run_tests``.

Issue #238 / #227: bare test names like ``test_issue_12420`` must be expanded
to ``<path>::test_issue_12420`` node IDs before being passed to pytest.  The
resolver only runs for repos in ``_REPOS_WITH_BARE_TEST_NAMES``; everything
else passes through unchanged.
"""

from __future__ import annotations

import subprocess
import types
from pathlib import Path

import pytest

from swebench import harness


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_collect_only_output(node_ids: list[str], extra: str = "") -> str:
    """Compose pytest --collect-only -q output containing the given node IDs."""
    lines = list(node_ids)
    if extra:
        lines.append(extra)
    # Always end with the summary line pytest emits.
    lines.append(f"{len(node_ids)} tests collected in 0.42s")
    return "\n".join(lines) + "\n"


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ---------------------------------------------------------------------------
# _looks_like_bare_test_name
# ---------------------------------------------------------------------------


def test_bare_test_name_recognised():
    assert harness._looks_like_bare_test_name("test_issue_12420")
    assert harness._looks_like_bare_test_name("test_latex_log")


def test_path_token_is_not_bare():
    assert not harness._looks_like_bare_test_name("sympy/printing/tests/test_x.py")


def test_node_id_token_is_not_bare():
    assert not harness._looks_like_bare_test_name("foo.py::test_x")


def test_flag_token_is_not_bare():
    assert not harness._looks_like_bare_test_name("-x")
    assert not harness._looks_like_bare_test_name("--collect-only")


def test_non_test_prefix_is_not_bare():
    # Don't rewrite arbitrary positional args that happen to look like words.
    assert not harness._looks_like_bare_test_name("foo")
    assert not harness._looks_like_bare_test_name("verbose")


# ---------------------------------------------------------------------------
# resolve_test_node_ids — non-sympy repos pass through
# ---------------------------------------------------------------------------


def test_non_sympy_repo_passes_through(monkeypatch, tmp_path: Path):
    """Repos not on the allow-list must never have their command rewritten."""
    def _boom(*a, **kw):  # pragma: no cover — should never be called
        raise AssertionError("subprocess.run must not be invoked for non-sympy repos")

    monkeypatch.setattr(subprocess, "run", _boom)
    cmd = "python -m pytest test_something"
    out = harness.resolve_test_node_ids(
        cmd,
        repo_dir=str(tmp_path),
        venv_dir=str(tmp_path / "venv"),
        repo_slug="django/django",
    )
    assert out == cmd


def test_no_repo_slug_passes_through(monkeypatch, tmp_path: Path):
    def _boom(*a, **kw):  # pragma: no cover
        raise AssertionError("subprocess.run must not be invoked when repo_slug is None")

    monkeypatch.setattr(subprocess, "run", _boom)
    cmd = "python -m pytest test_something"
    out = harness.resolve_test_node_ids(
        cmd,
        repo_dir=str(tmp_path),
        venv_dir=str(tmp_path / "venv"),
        repo_slug=None,
    )
    assert out == cmd


def test_non_pytest_command_passes_through(monkeypatch, tmp_path: Path):
    """Even for sympy, a non-pytest command must pass through unchanged."""
    def _boom(*a, **kw):  # pragma: no cover
        raise AssertionError("non-pytest command should not trigger resolution")

    monkeypatch.setattr(subprocess, "run", _boom)
    cmd = "python tests/runtests.py test_x"
    out = harness.resolve_test_node_ids(
        cmd,
        repo_dir=str(tmp_path),
        venv_dir=str(tmp_path / "venv"),
        repo_slug="sympy/sympy",
    )
    assert out == cmd


# ---------------------------------------------------------------------------
# resolve_test_node_ids — sympy with successful resolution
# ---------------------------------------------------------------------------


def test_sympy_bare_name_is_rewritten(monkeypatch, tmp_path: Path):
    """Sympy + bare test name → command rewritten with node IDs."""
    def _fake_run(cmd, **kw):
        # Confirm we ARE calling pytest --collect-only.
        assert "--collect-only" in cmd
        assert "test_issue_12420" in cmd
        return _FakeCompleted(
            returncode=0,
            stdout=_fake_collect_only_output(
                ["sympy/simplify/tests/test_sqrtdenest.py::test_issue_12420"]
            ),
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    out = harness.resolve_test_node_ids(
        "python -m pytest test_issue_12420",
        repo_dir=str(tmp_path),
        venv_dir=str(tmp_path / "venv"),
        repo_slug="sympy/sympy",
    )
    assert out == (
        "python -m pytest "
        "sympy/simplify/tests/test_sqrtdenest.py::test_issue_12420"
    )


def test_sympy_multiple_node_ids_all_collected(monkeypatch, tmp_path: Path):
    """When one bare name matches multiple files, all node IDs are emitted."""
    def _fake_run(cmd, **kw):
        return _FakeCompleted(
            returncode=0,
            stdout=_fake_collect_only_output([
                "sympy/a/test_x.py::test_foo",
                "sympy/b/test_y.py::test_foo",
            ]),
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    out = harness.resolve_test_node_ids(
        "python -m pytest test_foo",
        repo_dir=str(tmp_path),
        venv_dir=str(tmp_path / "venv"),
        repo_slug="sympy/sympy",
    )
    # Both node IDs appear in the rewritten command.
    assert "sympy/a/test_x.py::test_foo" in out
    assert "sympy/b/test_y.py::test_foo" in out


# ---------------------------------------------------------------------------
# resolve_test_node_ids — sympy with failed resolution (fall through)
# ---------------------------------------------------------------------------


def test_sympy_zero_results_leaves_bare_name(monkeypatch, tmp_path: Path):
    """Resolution that returns 0 node IDs must leave the bare name in place
    so the pre-flight check downstream can detect the env failure."""
    def _fake_run(cmd, **kw):
        # pytest exits 5 when nothing collected.
        return _FakeCompleted(returncode=5, stdout="no tests ran in 0.05s\n")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    cmd = "python -m pytest test_missing"
    out = harness.resolve_test_node_ids(
        cmd,
        repo_dir=str(tmp_path),
        venv_dir=str(tmp_path / "venv"),
        repo_slug="sympy/sympy",
    )
    assert out == cmd


def test_sympy_collector_error_leaves_command_unchanged(monkeypatch, tmp_path: Path):
    """A pytest crash (exit != 0 and != 5) yields no node IDs; command is unchanged."""
    def _fake_run(cmd, **kw):
        return _FakeCompleted(returncode=4, stdout="", stderr="usage error")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    cmd = "python -m pytest test_x"
    out = harness.resolve_test_node_ids(
        cmd,
        repo_dir=str(tmp_path),
        venv_dir=str(tmp_path / "venv"),
        repo_slug="sympy/sympy",
    )
    assert out == cmd


# ---------------------------------------------------------------------------
# run_preflight_collect
# ---------------------------------------------------------------------------


def test_preflight_returns_true_when_items_collected(monkeypatch, tmp_path: Path):
    def _fake_run(cmd, **kw):
        # Confirm we issue a pytest --collect-only call.
        assert "--collect-only" in cmd
        return _FakeCompleted(
            returncode=0,
            stdout=_fake_collect_only_output(["a/test_x.py::test_one"]),
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    ok, _ = harness.run_preflight_collect(
        repo_dir=str(tmp_path),
        test_cmd="python -m pytest a/test_x.py::test_one",
        venv_dir=str(tmp_path / "venv"),
    )
    assert ok is True


def test_preflight_returns_false_on_zero_collection(monkeypatch, tmp_path: Path):
    def _fake_run(cmd, **kw):
        return _FakeCompleted(
            returncode=5,
            stdout="no tests ran in 0.05s\n",
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    ok, _ = harness.run_preflight_collect(
        repo_dir=str(tmp_path),
        test_cmd="python -m pytest test_missing",
        venv_dir=str(tmp_path / "venv"),
    )
    assert ok is False


def test_preflight_returns_false_on_pytest_error(monkeypatch, tmp_path: Path):
    """Any non-zero exit that isn't accompanied by collected items is env_fail."""
    def _fake_run(cmd, **kw):
        return _FakeCompleted(
            returncode=3,
            stdout="ERROR: import error in conftest\n",
            stderr="Traceback ...",
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    ok, output = harness.run_preflight_collect(
        repo_dir=str(tmp_path),
        test_cmd="python -m pytest test_x",
        venv_dir=str(tmp_path / "venv"),
    )
    assert ok is False
    assert "Traceback" in output


def test_preflight_non_pytest_command_passes(monkeypatch, tmp_path: Path):
    """unittest-style invocations are not gated by the pre-flight."""
    def _boom(*a, **kw):  # pragma: no cover
        raise AssertionError("non-pytest command should not trigger collection")

    monkeypatch.setattr(subprocess, "run", _boom)
    ok, output = harness.run_preflight_collect(
        repo_dir=str(tmp_path),
        test_cmd="python tests/runtests.py test_x",
        venv_dir=str(tmp_path / "venv"),
    )
    assert ok is True
    assert output == ""
