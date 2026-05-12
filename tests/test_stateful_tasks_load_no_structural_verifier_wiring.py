"""Integration tests for stateful_reasoning task loading after structural_verifier removal.

Scenario: slice-stateful-tasks-load-no-structural-verifier
Tier: wiring

Verifies the full vertical slice: artifact_cli.py -> artifact_loader.load_tasks()
for the real problems/artifact/stateful_reasoning/ directory, after the
structural_verifier field was removed from event_ledger, unreachable_functions,
and upgrade_impact task.yaml files (issue #188).

What these tests detect:
  - If load_tasks() starts requiring structural_verifier (regression), these fail.
  - If any of the 3 modified task.yaml files become malformed (missing required
    field, bad instance_id, unknown category), these fail.
  - If structural_verifier is not parsed as None for tasks that omit it, type
    contract test fails.

These tests are fully offline and use the real on-disk task files.
No @pytest.mark.integration needed — sub-second, no network, no containers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swebench.artifact_loader import load_tasks
from swebench.artifact_models import Task

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
# load_tasks expects the root of <category>/<slug>/task.yaml — i.e. problems/artifact/
_ARTIFACT_ROOT = _REPO_ROOT / "problems" / "artifact"
_STATEFUL_DIR = _ARTIFACT_ROOT / "stateful_reasoning"

_MODIFIED_IDS = {
    "stateful_reasoning__event_ledger",
    "stateful_reasoning__unreachable_functions",
    "stateful_reasoning__upgrade_impact",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_stateful_reasoning_dir_exists() -> None:
    """Structural: problems/artifact/stateful_reasoning/ directory must exist."""
    assert _STATEFUL_DIR.is_dir(), (
        f"Expected stateful_reasoning task directory at {_STATEFUL_DIR}"
    )


def test_load_tasks_returns_list_for_stateful_reasoning() -> None:
    """load_tasks() on the artifact root must include stateful_reasoning tasks.

    load_tasks() expects the root that contains <category>/<slug>/task.yaml.
    Filtering to the 3 modified IDs verifies that event_ledger, unreachable_functions,
    and upgrade_impact all parse successfully from their task.yaml files.
    """
    tasks = load_tasks(_ARTIFACT_ROOT, filter_ids=_MODIFIED_IDS)
    assert isinstance(tasks, list)
    assert len(tasks) == len(_MODIFIED_IDS), (
        f"Expected {len(_MODIFIED_IDS)} stateful_reasoning tasks to load, "
        f"got {len(tasks)}: {[t.instance_id for t in tasks]}"
    )


def test_modified_tasks_all_present() -> None:
    """The 3 modified tasks must all appear in the loaded task list."""
    tasks = load_tasks(_ARTIFACT_ROOT, filter_ids=_MODIFIED_IDS)
    loaded_ids = {t.instance_id for t in tasks}
    missing = _MODIFIED_IDS - loaded_ids
    assert not missing, (
        f"Modified tasks not found in stateful_reasoning task load: {sorted(missing)}"
    )


def test_modified_tasks_structural_verifier_is_none() -> None:
    """All 3 modified tasks must have structural_verifier=None after removal."""
    tasks = load_tasks(_ARTIFACT_ROOT, filter_ids=_MODIFIED_IDS)
    task_map = {t.instance_id: t for t in tasks}
    for iid in _MODIFIED_IDS:
        assert iid in task_map, f"Task {iid!r} not found"
        task = task_map[iid]
        assert task.structural_verifier is None, (
            f"Expected structural_verifier=None for {iid!r}, "
            f"got {task.structural_verifier!r}"
        )


def test_modified_tasks_have_correct_category() -> None:
    """All 3 modified tasks must have category='stateful_reasoning'."""
    tasks = load_tasks(_ARTIFACT_ROOT, filter_ids=_MODIFIED_IDS)
    task_map = {t.instance_id: t for t in tasks}
    for iid in _MODIFIED_IDS:
        assert iid in task_map
        task = task_map[iid]
        assert task.category == "stateful_reasoning", (
            f"Task {iid!r}: expected category='stateful_reasoning', "
            f"got {task.category!r}"
        )


def test_event_ledger_has_workspace_generator() -> None:
    """event_ledger must retain workspace_generator after structural_verifier removal."""
    tasks = load_tasks(_ARTIFACT_ROOT, filter_ids={"stateful_reasoning__event_ledger"})
    assert len(tasks) == 1, "event_ledger task not found"
    el = tasks[0]
    assert el.workspace_generator is not None, (
        "event_ledger must still declare workspace_generator after structural_verifier removal"
    )
    assert isinstance(el.workspace_generator, str)


def test_tasks_sorted_by_instance_id() -> None:
    """load_tasks() with filter must return tasks in instance_id-sorted order."""
    tasks = load_tasks(_ARTIFACT_ROOT, filter_ids=_MODIFIED_IDS)
    ids = [t.instance_id for t in tasks]
    assert ids == sorted(ids), (
        f"Tasks not sorted by instance_id: {ids}"
    )


def test_load_tasks_with_filter_for_modified_ids() -> None:
    """load_tasks() with filter_ids must return exactly the 3 modified tasks."""
    tasks = load_tasks(_ARTIFACT_ROOT, filter_ids=_MODIFIED_IDS)
    loaded_ids = {t.instance_id for t in tasks}
    assert loaded_ids == _MODIFIED_IDS, (
        f"Filtered load returned {loaded_ids!r}, expected {_MODIFIED_IDS!r}"
    )


def test_task_model_type_for_each_modified_task() -> None:
    """Each loaded task must be a Task instance with the correct field types."""
    tasks = load_tasks(_ARTIFACT_ROOT, filter_ids=_MODIFIED_IDS)
    for task in tasks:
        assert isinstance(task, Task)
        assert isinstance(task.instance_id, str)
        assert isinstance(task.category, str)
        assert isinstance(task.difficulty, str)
        assert task.difficulty in {"easy", "medium", "hard"}
        # structural_verifier must be None or str — after removal, must be None
        assert task.structural_verifier is None
        # execution_budget must be present
        assert task.execution_budget is not None
        assert isinstance(task.execution_budget.max_code_runs, int)
        assert isinstance(task.execution_budget.max_wall_seconds, int)
