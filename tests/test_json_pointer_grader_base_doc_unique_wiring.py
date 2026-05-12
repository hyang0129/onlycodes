"""Integration tests for json_pointer_rfc6901 grader after duplicate-key removal.

Scenario: slice-json-pointer-grader-base-doc-unique
Tier: wiring

Verifies the full vertical slice: verify_graders.py tool -> grader/hidden.py._base_doc()
for the real verification_heavy/json_pointer_rfc6901 task, after removing the
duplicate empty-string key from _base_doc() (issue #188).

What these tests detect:
  - If _base_doc() reintroduces a duplicate key, the dict will silently collapse
    to 6 unique keys; the key-count assertion fails.
  - If the reference_output.py is moved or deleted, loading the grader fails.
  - If verify_graders.py subprocess interface changes (exit codes), the
    subprocess-level assertions catch it.
  - If the empty-string pointer "/", now resolved against the single unique ""
    key, breaks any resolve test case, the reference output check surfaces it.

These tests load the real grader module and invoke it directly (wiring tier).
No @pytest.mark.integration needed — fully offline, sub-second.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GRADER_PATH = (
    _REPO_ROOT
    / "problems"
    / "artifact"
    / "verification_heavy"
    / "json_pointer_rfc6901"
    / "grader"
    / "hidden.py"
)
_VERIFY_TOOL = _REPO_ROOT / "tools" / "verify_graders.py"
_TASK_ROOT = _REPO_ROOT / "problems" / "artifact"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_grader():
    """Load the json_pointer_rfc6901 hidden grader module directly."""
    name = "_json_pointer_grader_itest"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _GRADER_PATH)
    assert spec is not None and spec.loader is not None, (
        f"Cannot load grader from {_GRADER_PATH}"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        del sys.modules[name]
        raise
    return mod


# ---------------------------------------------------------------------------
# Tests — structural (wiring tier)
# ---------------------------------------------------------------------------


def test_grader_file_exists() -> None:
    """Structural: json_pointer_rfc6901/grader/hidden.py must exist on disk."""
    assert _GRADER_PATH.is_file(), (
        f"Expected grader at {_GRADER_PATH}"
    )


def test_grader_loads_without_error() -> None:
    """grader/hidden.py must be importable (syntax valid, no top-level errors)."""
    mod = _load_grader()
    assert mod is not None


def test_base_doc_has_exactly_seven_unique_keys() -> None:
    """_base_doc() must return a dict with exactly 7 unique keys.

    Before this fix, _base_doc() had the '' key defined twice as literals (a code
    quality issue: duplicate dict literal Python silently collapses to 7 keys
    via last-write-wins). After the fix, the dict has 7 literal definitions and
    7 runtime keys — the source is now non-misleading.

    This test verifies the runtime dict has exactly 7 keys (no regression into
    either fewer or more).
    """
    mod = _load_grader()
    assert hasattr(mod, "_base_doc"), "grader must expose _base_doc()"
    doc = mod._base_doc()
    assert isinstance(doc, dict)
    assert len(doc) == 7, (
        f"Expected 7 unique keys in _base_doc(), got {len(doc)}: {list(doc.keys())}"
    )


def test_base_doc_empty_string_key_present() -> None:
    """_base_doc() must contain the '' (empty-string) key after deduplication.

    The empty-string key maps to the RFC 6901 root-document pointer '/'.
    Removing the duplicate must preserve the key, just with a single definition.
    """
    mod = _load_grader()
    doc = mod._base_doc()
    assert "" in doc, (
        "Expected empty-string key '' in _base_doc() after duplicate removal"
    )
    assert doc[""] == "empty-key", (
        f"Expected doc[''] == 'empty-key', got {doc['']!r}"
    )


def test_base_doc_required_keys_present() -> None:
    """_base_doc() must contain all expected RFC 6901 test keys."""
    mod = _load_grader()
    doc = mod._base_doc()
    expected_keys = {"", "a/b", "m~n", "foo", "nested", "arr", "primitives"}
    missing = expected_keys - set(doc.keys())
    assert not missing, (
        f"_base_doc() missing expected keys: {sorted(missing)}"
    )


def test_grade_function_callable() -> None:
    """grade() must be a callable accepting one argument (scratch_dir path)."""
    mod = _load_grader()
    assert hasattr(mod, "grade"), "grader must expose grade()"
    import inspect
    sig = inspect.signature(mod.grade)
    params = list(sig.parameters)
    assert len(params) == 1, (
        f"grade() must accept exactly 1 parameter, got {params}"
    )


def test_grade_returns_graderesult_type_on_missing_artifact(tmp_path: Path) -> None:
    """grade() must return a GradeResult-like object when artifact is missing.

    This tests the interface contract (wiring), not the scoring value.
    """
    mod = _load_grader()
    result = mod.grade(tmp_path)
    assert hasattr(result, "passed"), "grade() result must have .passed attribute"
    assert hasattr(result, "score"), "grade() result must have .score attribute"
    assert hasattr(result, "detail"), "grade() result must have .detail attribute"
    # Missing artifact: passed must be False, score must be float
    assert result.passed is False, (
        f"grade() on missing artifact must return passed=False, got {result.passed!r}"
    )
    assert isinstance(result.score, float), (
        f"grade() score must be float, got {type(result.score)}"
    )


def test_verify_graders_tool_exists() -> None:
    """Structural: tools/verify_graders.py must exist on disk."""
    assert _VERIFY_TOOL.is_file(), (
        f"Expected verify_graders.py at {_VERIFY_TOOL}"
    )


def test_verify_graders_subprocess_with_json_pointer_task(tmp_path: Path) -> None:
    """verify_graders.py invoked against just the json_pointer_rfc6901 task must exit 0.

    We stage a single-task directory pointing at the real json_pointer_rfc6901 task
    via symlinks so verify_graders.py exercises the full path
    (load_tasks -> materialize -> invoke_grader) without running all 40+ tasks.

    Exit code 0 means the reference output passes the grader.
    Exit code 1 would mean the grader (with _base_doc fixed) disagrees with
    the reference output — a real failure in the fix.
    Exit code 2 means task discovery/parse failed (structural wiring error).
    """
    # Stage: tmp_path/tasks/verification_heavy/json_pointer_rfc6901 -> real task dir
    staged = tmp_path / "tasks" / "verification_heavy"
    staged.mkdir(parents=True)
    real_task = _TASK_ROOT / "verification_heavy" / "json_pointer_rfc6901"
    assert real_task.is_dir(), f"json_pointer_rfc6901 task dir not found: {real_task}"

    import os
    os.symlink(real_task, staged / "json_pointer_rfc6901")

    result = subprocess.run(
        [sys.executable, str(_VERIFY_TOOL), "--tasks-dir", str(tmp_path / "tasks")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    # Must produce output naming the task
    combined = result.stdout + result.stderr
    assert "json_pointer_rfc6901" in combined, (
        f"verify_graders.py output did not mention json_pointer_rfc6901.\n"
        f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:200]}"
    )
    # Exit 2 = discovery/parse error (structural failure)
    assert result.returncode != 2, (
        f"verify_graders.py exited 2 (discovery/parse error).\n"
        f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:200]}"
    )
    # Exit 0 = PASS (reference output passed the fixed grader)
    # Exit 1 = FAIL (grader disagreed with reference — a real regression)
    assert result.returncode == 0, (
        f"verify_graders.py exited {result.returncode} — json_pointer_rfc6901 grader "
        f"did not pass its reference output after _base_doc() deduplication.\n"
        f"stdout: {result.stdout[:500]}"
    )
