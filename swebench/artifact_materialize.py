"""Workspace materialization for artifact-graded benchmark tasks.

ABSOLUTE invariant (see SCHEMA §5 and refined spec Q3): the agent's scratch
dir contains ONLY the contents of ``workspace/`` (plus whatever the agent
writes at run time). ``grader/`` and ``reference_output.*`` MUST NEVER be
copied in. A post-copy scan enforces this invariant.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from swebench.artifact_models import Task


class MaterializationError(RuntimeError):
    """Raised when the no-leak invariant is violated after copytree."""


def scratch_dir_for(
    results_dir: Path,
    instance_id: str,
    arm: str,
    run_idx: int,
) -> Path:
    """Return the canonical scratch-dir path (not created)."""
    return results_dir / instance_id / arm / f"run{run_idx}" / "scratch"


def materialize(task: Task, scratch_dir: Path) -> Path:
    """Copy ``task.workspace_dir`` into ``scratch_dir``.

    - Uses ``shutil.copytree(..., dirs_exist_ok=True)``.
    - Never copies ``task_dir/grader/`` or any ``reference_output*`` file.
    - Raises ``MaterializationError`` if a post-copy scan finds a grader leak.

    Returns the absolute path to the populated scratch dir.
    """
    if task.task_dir is None:
        raise ValueError(f"Task {task.instance_id!r} has no task_dir attached")

    workspace_src = task.task_dir / task.workspace_dir
    if not workspace_src.is_dir():
        raise FileNotFoundError(
            f"workspace_dir does not exist: {workspace_src}"
        )

    scratch_dir = scratch_dir.resolve()
    scratch_dir.mkdir(parents=True, exist_ok=True)

    # We only copy workspace/. grader/ is left behind by construction.
    shutil.copytree(workspace_src, scratch_dir, dirs_exist_ok=True, symlinks=False)

    _assert_no_grader_leak(scratch_dir)
    return scratch_dir


def _assert_no_grader_leak(scratch_dir: Path) -> None:
    """Fail loudly if any grader artifact leaked into the agent's scratch dir."""
    # "hidden.py" is the grader's module filename; reference_output.* is the
    # golden artifact. Either appearing inside the scratch dir is a bug.
    leaks: list[Path] = []
    for path in scratch_dir.rglob("*"):
        if not path.is_file():
            continue
        name = path.name
        if name == "hidden.py":
            leaks.append(path)
        elif name.startswith("reference_output"):
            leaks.append(path)
    if leaks:
        rels = [str(p.relative_to(scratch_dir)) for p in leaks]
        raise MaterializationError(
            f"No-leak invariant violated in {scratch_dir}: {rels}"
        )
