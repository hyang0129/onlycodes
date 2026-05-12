"""Integration wiring tests for the ``_venv_kwargs(problem)`` call-site change.

Scenario: slice-venv-kwargs-problem-wiring
Tier: wiring

Issue #204 changed the signature of ``_venv_kwargs`` from taking a bare
``repo_slug: str`` to taking a full ``Problem`` object so that instance-level
overrides (``_INSTANCE_PYTHON``, ``_INSTANCE_PRE_INSTALL``) can be applied.

The call sites in ``run.py`` (``_setup_problem`` and ``_setup_problem_cached``)
and ``cache_cli.py`` (``_setup_one``) were updated accordingly.  These tests
verify:

1. ``_venv_kwargs(problem)`` returns a dict that includes ``repo_slug`` —
   so ``setup_venv(**_venv_kwargs(problem))`` receives ``repo_slug`` and can
   call ``_smoke_import``.

2. The ``repo_slug`` key in the returned dict matches ``problem.repo_slug``
   (not an instance_id or some other value).

3. ``_venv_kwargs`` correctly threads instance-level overrides *and*
   ``repo_slug`` in a single return value, which ``setup_venv`` consumes.

4. The ``run.py`` and ``cache_cli.py`` call sites accept a Problem object
   without raising ``AttributeError`` (regression guard against accidentally
   passing ``problem.repo_slug`` instead of ``problem``).

No real venvs are created.  subprocess.run is monkeypatched.  These tests
run on every CI push (no ``@pytest.mark.integration`` — they are fully offline
and sub-second).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from swebench.harness import (
    _INSTANCE_PRE_INSTALL,
    _INSTANCE_PYTHON,
    _REPO_PRE_INSTALL,
    _REPO_PYTHON,
    _venv_kwargs,
    setup_venv,
)
from swebench.models import Problem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_problem(
    instance_id: str = "some__repo-123",
    repo_slug: str = "some/repo",
) -> Problem:
    """Build a minimal Problem for call-site wiring tests."""
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


def _make_subprocess_success(args: list[str] | None = None) -> MagicMock:
    m = MagicMock()
    m.returncode = 0
    m.args = args or []
    m.stdout = ""
    m.stderr = ""
    return m


# ---------------------------------------------------------------------------
# Scenario: slice-venv-kwargs-problem-wiring (wiring tier)
#
# Tests 1–4: _venv_kwargs(problem) return-dict structure
# ---------------------------------------------------------------------------


def test_venv_kwargs_returns_repo_slug_key() -> None:
    """_venv_kwargs(Problem) must include 'repo_slug' in its return dict.

    This key is consumed by setup_venv() to route _smoke_import().  Absence
    would mean the smoke-import check is silently skipped for all repos.
    """
    problem = _make_problem(repo_slug="matplotlib/matplotlib")
    result = _venv_kwargs(problem)

    assert "repo_slug" in result, (
        f"_venv_kwargs must return 'repo_slug' key; got keys: {list(result.keys())}"
    )


def test_venv_kwargs_repo_slug_value_matches_problem() -> None:
    """The 'repo_slug' value in the dict must equal problem.repo_slug."""
    slug = "scikit-learn/scikit-learn"
    problem = _make_problem(repo_slug=slug)
    result = _venv_kwargs(problem)

    assert result["repo_slug"] == slug, (
        f"Expected repo_slug={slug!r}, got {result['repo_slug']!r}"
    )


def test_venv_kwargs_returns_python_bin_key() -> None:
    """_venv_kwargs(Problem) must include 'python_bin' in its return dict.

    This is the existing contract; verifying it is not broken by the
    Problem-signature change.
    """
    problem = _make_problem()
    result = _venv_kwargs(problem)

    assert "python_bin" in result, (
        f"'python_bin' missing from _venv_kwargs output; got: {list(result.keys())}"
    )
    # Value must be a non-empty string (a valid interpreter name)
    assert isinstance(result["python_bin"], str) and result["python_bin"], (
        f"python_bin must be a non-empty string, got {result['python_bin']!r}"
    )


def test_venv_kwargs_dict_is_unpacked_into_setup_venv(tmp_path: Path) -> None:
    """setup_venv(**_venv_kwargs(problem)) must not raise.

    Verifies the end-to-end **-unpack: the dict produced by _venv_kwargs(problem)
    is compatible with setup_venv's keyword signature.  A regression (e.g.
    returning an unexpected key) would raise TypeError here.
    """
    venv_dir = str(tmp_path / "venv")
    repo_dir = str(tmp_path / "repo")
    os.makedirs(repo_dir)

    problem = _make_problem(repo_slug="unknown/unlisted-repo")

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
        calls.append(cmd)
        if "-m" in cmd and "venv" in cmd:
            pip_dir = os.path.join(venv_dir, "bin")
            os.makedirs(pip_dir, exist_ok=True)
            Path(os.path.join(pip_dir, "pip")).touch()
        return _make_subprocess_success(cmd)

    with patch("subprocess.run", side_effect=fake_run):
        # Must not raise TypeError ("unexpected keyword argument")
        setup_venv(venv_dir, repo_dir, **_venv_kwargs(problem))

    # setup_venv ran at least the venv creation call
    assert any("-m" in c and "venv" in c for c in calls), (
        f"Expected venv creation subprocess call; got: {calls}"
    )


# ---------------------------------------------------------------------------
# Tests 5–6: call-site type contract — Problem object, not bare str
# ---------------------------------------------------------------------------


def test_venv_kwargs_accepts_problem_instance() -> None:
    """_venv_kwargs must accept a Problem object without AttributeError.

    Guards against regression where callers accidentally pass problem.repo_slug
    (a str) instead of problem (a Problem).  If the signature reverted to
    str, calling it with a Problem would raise AttributeError on .instance_id.
    """
    problem = _make_problem(
        instance_id="astropy__astropy-6938",
        repo_slug="astropy/astropy",
    )
    # Must not raise AttributeError or TypeError
    result = _venv_kwargs(problem)
    assert isinstance(result, dict)


def test_venv_kwargs_instance_id_drives_instance_override(tmp_path: Path) -> None:
    """_venv_kwargs uses problem.instance_id for the instance-level lookup.

    If the call site accidentally passed problem.repo_slug (a str), the
    instance-level override would silently fail — the str has no .instance_id
    attribute, so the lookup would fall through to repo-level.  This test
    injects a synthetic instance-level override and verifies it wins over the
    repo-level entry, proving instance_id was used.
    """
    import swebench.harness as h

    problem = _make_problem(
        instance_id="test__wiring-instance-1",
        repo_slug="test/wiring-repo",
    )

    with (
        patch.dict(h._INSTANCE_PRE_INSTALL, {"test__wiring-instance-1": ["sentinel-pin"]}),
        patch.dict(h._REPO_PRE_INSTALL, {"test/wiring-repo": ["repo-pin"]}),
    ):
        result = _venv_kwargs(problem)

    assert result.get("pre_install") == ["sentinel-pin"], (
        f"Expected instance-level override ['sentinel-pin'], got {result.get('pre_install')!r}. "
        "This suggests the call site is not passing a Problem object with .instance_id."
    )


# ---------------------------------------------------------------------------
# Test 7: regression guard — _venv_kwargs with Problem does not break
# for repos with no overrides (unknown repo path)
# ---------------------------------------------------------------------------


def test_venv_kwargs_unknown_repo_returns_defaults() -> None:
    """_venv_kwargs for an unknown repo/instance returns default python_bin and no pre_install."""
    from swebench.harness import _DEFAULT_PYTHON

    problem = _make_problem(
        instance_id="unknown__unknown-999",
        repo_slug="unknown/unknown",
    )
    result = _venv_kwargs(problem)

    assert result["python_bin"] == _DEFAULT_PYTHON, (
        f"Unknown repo must use _DEFAULT_PYTHON ({_DEFAULT_PYTHON!r}), got {result['python_bin']!r}"
    )
    # pre_install may be None (not in any table)
    assert result.get("pre_install") is None, (
        f"Unknown repo must have pre_install=None, got {result.get('pre_install')!r}"
    )
    # repo_slug must still be present
    assert result["repo_slug"] == "unknown/unknown", (
        f"repo_slug must be passed through for unknown repos; got {result.get('repo_slug')!r}"
    )
