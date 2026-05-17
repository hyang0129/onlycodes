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


# ---------------------------------------------------------------------------
# Real-pytest integration: _collect_node_ids against an actual pytest run
# ---------------------------------------------------------------------------
# These tests do NOT monkeypatch subprocess. They exercise the resolver
# against a real pytest invocation on a minimal pytest tree. Without ``-k``,
# pytest treats a bare name as a path and exits 4 ("file or directory not
# found"), and the resolver returns []. With ``-k``, pytest walks the
# collection tree and emits node IDs whose name *contains* the bare token;
# the resolver's post-filter on exact-name equality narrows to the right one.


def _write_pytest_tree(root: Path) -> None:
    """Create a minimal two-file pytest tree under *root*.

    test_alpha.py contains two tests whose names both contain the resolver
    target — this verifies the exact-name post-filter discards ``-k`` over-
    matches. test_beta.py contains an unrelated test.
    """
    (root / "tests").mkdir()
    (root / "tests" / "__init__.py").write_text("")
    (root / "tests" / "test_alpha.py").write_text(
        "def test_resolver_target_xyz():\n"
        "    assert True\n"
        "\n"
        "def test_resolver_target_xyz_extra():\n"
        "    assert True\n"
    )
    (root / "tests" / "test_beta.py").write_text(
        "def test_unrelated():\n"
        "    assert True\n"
    )
    # Empty conftest avoids pytest discovering an unrelated parent project.
    (root / "conftest.py").write_text("")


def test_collect_node_ids_real_pytest_finds_bare_name(tmp_path: Path):
    """Real pytest run: bare name resolves to its node ID via -k."""
    import sys as _sys
    _write_pytest_tree(tmp_path)
    node_ids = harness._collect_node_ids(
        str(tmp_path), _sys.executable, "test_resolver_target_xyz",
    )
    assert node_ids == ["tests/test_alpha.py::test_resolver_target_xyz"], (
        f"Expected exact-match node ID, got {node_ids!r}.  If this returned "
        f"[], the resolver is not using -k and pytest is exiting 4 on the "
        f"bare positional arg (Issue #238 regression)."
    )


def test_collect_node_ids_real_pytest_missing_name_returns_empty(tmp_path: Path):
    """Real pytest run: a bare name with no matching test yields []."""
    import sys as _sys
    _write_pytest_tree(tmp_path)
    node_ids = harness._collect_node_ids(
        str(tmp_path), _sys.executable, "test_no_such_function_anywhere",
    )
    assert node_ids == []


# ---------------------------------------------------------------------------
# Issue #262: parametrized node IDs with parens / spaces / commas
# ---------------------------------------------------------------------------


def test_node_id_regex_matches_parametrized_id_with_parens_and_spaces():
    """``test_unparse[(1, 2, 3)-(1, 2, 3)]`` must match. The old character
    class ``[\\w\\[\\]\\-:]`` rejected ``(``/``)``/``,``/space and silently
    mis-classified collected tests as 0-items (Issue #262, sphinx-9367 / 8265).
    """
    sample = "tests/test_pycode_ast.py::test_unparse[(1, 2, 3)-(1, 2, 3)]\n"
    m = harness._NODE_ID_LINE_RE.search(sample)
    assert m is not None, "regex should match parametrized id with parens/spaces"
    assert m.group("path") == "tests/test_pycode_ast.py"
    assert m.group("name") == "test_unparse[(1, 2, 3)-(1, 2, 3)]"


def test_node_id_regex_still_matches_simple_function_id():
    """Regression guard: simple ``file.py::test_fn`` still matches."""
    m = harness._NODE_ID_LINE_RE.search("a/test_x.py::test_one\n")
    assert m is not None
    assert m.group("name") == "test_one"


def test_node_id_regex_still_matches_class_method_id():
    """Regression guard: class-level node IDs still match."""
    m = harness._NODE_ID_LINE_RE.search(
        "tests/x.py::TestClass::test_method\n"
    )
    assert m is not None
    assert m.group("name") == "TestClass::test_method"


def test_node_id_regex_matches_single_element_tuple_param():
    """The sister case to 8265: ``[(1,)-(1,)]`` from sphinx-9367 — commas
    inside parens, no spaces. Must also match.
    """
    m = harness._NODE_ID_LINE_RE.search(
        "tests/test_pycode_ast.py::test_unparse[(1,)-(1,)]\n"
    )
    assert m is not None
    assert m.group("name") == "test_unparse[(1,)-(1,)]"


def test_preflight_shlex_split_handles_quoted_node_id(monkeypatch, tmp_path: Path):
    """A YAML ``test_cmd`` that quotes a parametrized node ID containing
    spaces must reach pytest as ONE arg, not be shredded into six by naive
    ``str.split()`` (Issue #262).
    """
    captured: dict[str, list[str]] = {}

    def _fake_run(cmd, **kw):
        captured["cmd"] = list(cmd)
        return _FakeCompleted(
            returncode=0,
            stdout=_fake_collect_only_output(
                ["tests/test_pycode_ast.py::test_unparse[(1, 2, 3)-(1, 2, 3)]"]
            ),
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    ok, _ = harness.run_preflight_collect(
        repo_dir=str(tmp_path),
        test_cmd=(
            'python -m pytest '
            '"tests/test_pycode_ast.py::test_unparse[(1, 2, 3)-(1, 2, 3)]"'
        ),
        venv_dir=str(tmp_path / "venv"),
    )
    assert ok is True
    # Verify the quoted arg arrived as a single token (not 6 fragments).
    cmd = captured["cmd"]
    assert (
        "tests/test_pycode_ast.py::test_unparse[(1, 2, 3)-(1, 2, 3)]" in cmd
    ), f"quoted node ID was split; got cmd={cmd!r}"
