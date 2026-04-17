"""Shared pytest fixtures for the onlycodes test suite.

The primary fixture here is an autouse guard that asserts the repo-root
``patterns.json`` file (the canonical pathology vocabulary, written by
sub-issue #74) is not mutated by any test. Even before that file exists,
the guard detects accidental creation.

Rationale: ``patterns.json`` is a shared, version-controlled artefact used
across the analysis pipeline. A test that writes to it would silently leak
state into every subsequent run of the suite and into the developer's
working tree. Failing loudly is the only acceptable behaviour.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from swebench import repo_root


def _snapshot(path: Path) -> tuple[bool, str | None]:
    """Return ``(exists, sha256-hex-or-None)`` for ``path``."""
    if not path.exists():
        return (False, None)
    return (True, hashlib.sha256(path.read_bytes()).hexdigest())


@pytest.fixture(autouse=True)
def _patterns_json_is_immutable() -> None:
    """Fail any test that writes to or deletes the repo-root ``patterns.json``.

    The fixture snapshots existence + content hash before the test runs,
    then re-snapshots after and asserts equality. It is autouse so every
    test in the suite is protected without opt-in.
    """
    patterns_path = repo_root() / "patterns.json"
    before = _snapshot(patterns_path)
    yield
    after = _snapshot(patterns_path)
    assert before == after, (
        f"Test illegally mutated {patterns_path}: "
        f"before={before} after={after}. patterns.json is the canonical "
        "pathology vocabulary and must never be modified by the test suite."
    )
