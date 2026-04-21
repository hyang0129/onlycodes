"""Task loader for artifact-graded benchmark mode.

Walks ``problems/artifact/<category>/<slug>/task.yaml`` and parses each manifest per the
frozen SCHEMA in docs/SCHEMA_ARTIFACT.md.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import yaml

from swebench.artifact_models import ExecutionBudget, Task

_INSTANCE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*__[a-z0-9_]+$")

_CATEGORIES = frozenset({
    "data_processing",
    "algorithmic",
    "verification_heavy",
    "enumeration",
    "stateful_reasoning",
    "iterative_numerical",
    # Test-only category used by the fixture task in the test suite. Kept
    # permissive so synthetic fixtures don't require real task content.
    "test_fixture",
})

_DIFFICULTIES = frozenset({"easy", "medium"})

_REQUIRED_FIELDS = frozenset({
    "instance_id",
    "category",
    "difficulty",
    "problem_statement",
    "workspace_dir",
    "output_artifact",
    "hidden_grader",
    "reference_output",
    "execution_budget",
})

_OPTIONAL_FIELDS = frozenset({
    "structural_verifier",
    "workspace_generator",
    "tags",
})

_ALLOWED_FIELDS = _REQUIRED_FIELDS | _OPTIONAL_FIELDS


def _parse_task_yaml(path: Path) -> Task:
    """Parse a single task.yaml into a Task. Raises ValueError on schema violation."""
    with open(path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"{path}: task.yaml must be a mapping")

    keys = set(data.keys())
    unknown = keys - _ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"{path}: unknown field(s) in task.yaml: {sorted(unknown)}")
    missing = _REQUIRED_FIELDS - keys
    if missing:
        raise ValueError(f"{path}: missing required field(s): {sorted(missing)}")

    instance_id = str(data["instance_id"])
    if not _INSTANCE_ID_RE.match(instance_id):
        raise ValueError(
            f"{path}: instance_id {instance_id!r} does not match "
            f"{_INSTANCE_ID_RE.pattern}"
        )

    category = str(data["category"])
    if category not in _CATEGORIES:
        raise ValueError(f"{path}: unknown category {category!r}")
    if not instance_id.startswith(f"{category}__"):
        raise ValueError(
            f"{path}: instance_id {instance_id!r} does not start with "
            f"'{category}__' (category prefix mismatch)"
        )

    difficulty = str(data["difficulty"])
    if difficulty not in _DIFFICULTIES:
        raise ValueError(
            f"{path}: difficulty must be one of {sorted(_DIFFICULTIES)}, "
            f"got {difficulty!r}"
        )

    budget_raw = data["execution_budget"]
    if not isinstance(budget_raw, dict):
        raise ValueError(f"{path}: execution_budget must be a mapping")
    for k in ("max_code_runs", "max_wall_seconds"):
        if k not in budget_raw:
            raise ValueError(f"{path}: execution_budget missing {k}")
        v = budget_raw[k]
        if not isinstance(v, int) or v < 0:
            raise ValueError(
                f"{path}: execution_budget.{k} must be int >= 0, got {v!r}"
            )
    budget = ExecutionBudget(
        max_code_runs=int(budget_raw["max_code_runs"]),
        max_wall_seconds=int(budget_raw["max_wall_seconds"]),
    )

    tags_raw = data.get("tags", []) or []
    if not isinstance(tags_raw, list) or not all(isinstance(t, str) for t in tags_raw):
        raise ValueError(f"{path}: tags must be list[str]")

    structural_verifier = data.get("structural_verifier")
    if structural_verifier is not None and not isinstance(structural_verifier, str):
        raise ValueError(f"{path}: structural_verifier must be a string path")

    workspace_generator = data.get("workspace_generator")
    if workspace_generator is not None and not isinstance(workspace_generator, str):
        raise ValueError(f"{path}: workspace_generator must be a string path")

    return Task(
        instance_id=instance_id,
        category=category,
        difficulty=difficulty,
        problem_statement=str(data["problem_statement"]),
        workspace_dir=str(data["workspace_dir"]),
        output_artifact=str(data["output_artifact"]),
        hidden_grader=str(data["hidden_grader"]),
        reference_output=str(data["reference_output"]),
        execution_budget=budget,
        structural_verifier=structural_verifier,
        workspace_generator=workspace_generator,
        tags=list(tags_raw),
        task_dir=path.parent.resolve(),
    )


def discover_task_manifests(tasks_dir: Path) -> list[Path]:
    """Return sorted list of task.yaml paths under tasks_dir. Empty if none."""
    if not tasks_dir.is_dir():
        return []
    # Glob at depth 2: problems/artifact/<category>/<slug>/task.yaml
    return sorted(tasks_dir.glob("*/*/task.yaml"))


def load_tasks(
    tasks_dir: Path,
    filter_ids: Iterable[str] | None = None,
) -> list[Task]:
    """Load every task under ``tasks_dir``, optionally filtered by exact instance_id.

    Args:
        tasks_dir: root directory containing ``<category>/<slug>/task.yaml`` entries.
        filter_ids: if provided, only tasks whose ``instance_id`` is in this set
            are returned. Passing an empty iterable explicitly is treated like
            ``None`` (no filter) — callers pass ``None`` if they mean "all".

    Returns:
        List of Task in instance_id-sorted order.

    Raises:
        ValueError: if any task.yaml fails to parse, or if filter_ids is set
            but no tasks match.
    """
    manifests = discover_task_manifests(tasks_dir)
    tasks = [_parse_task_yaml(m) for m in manifests]
    tasks.sort(key=lambda t: t.instance_id)

    if filter_ids:
        wanted = {s.strip() for s in filter_ids if s and s.strip()}
        if wanted:
            selected = [t for t in tasks if t.instance_id in wanted]
            if not selected:
                raise ValueError(
                    f"No matching tasks for filter: {sorted(wanted)}"
                )
            return selected
    return tasks
