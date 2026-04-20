"""Grader invocation for artifact-graded benchmark tasks.

Runs the task's ``grader/hidden.py:grade(scratch_dir)`` in a fresh Python
subprocess so the grader has no shared state with the agent process and no
accidental access to agent sandbox leftovers. See refined spec Q7.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from swebench.artifact_models import GradeResult, Task


class GraderInvocationError(RuntimeError):
    """Raised when the grader subprocess fails with an infrastructure error.

    This is distinct from a grader returning ``passed=False`` — that is a
    task failure, not a harness failure. This exception is raised only when
    the grader itself could not be run (missing module, raised an exception,
    produced malformed output).
    """


def _grader_dir_for(task: Task) -> Path:
    """Resolve the absolute path to the task's grader/ directory."""
    if task.task_dir is None:
        raise ValueError(f"Task {task.instance_id!r} has no task_dir attached")
    grader_rel = task.hidden_grader  # e.g. "grader/hidden.py"
    return (task.task_dir / grader_rel).parent.resolve()


def invoke_grader(
    task: Task,
    scratch_dir: Path,
    *,
    timeout_seconds: float | None = 120.0,
    python_executable: str | None = None,
) -> GradeResult:
    """Invoke the task's grader on ``scratch_dir`` via a subprocess.

    Returns the parsed ``GradeResult``.

    Raises:
        GraderInvocationError: if the grader module is missing, raises an
            exception, or returns malformed output.
    """
    grader_dir = _grader_dir_for(task)
    if not (grader_dir / "hidden.py").is_file():
        raise GraderInvocationError(
            f"grader/hidden.py not found for task {task.instance_id} "
            f"(expected at {grader_dir / 'hidden.py'})"
        )

    python = python_executable or sys.executable

    # The grader subprocess is invoked as `python -m swebench._artifact_grade_runner`.
    # To make that import resolvable, we pass PYTHONPATH pointing at the repo
    # root (the parent of swebench/). This does NOT affect the agent — the
    # agent runs in a separate subprocess earlier, with a different cwd and
    # no `swebench.*` on its path.
    repo_root = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{repo_root}{os.pathsep}{existing}" if existing else str(repo_root)
    )
    # Offline hint to discourage accidental network I/O in graders. Not a
    # sandbox — just a signal. (Seed-stage: no kernel isolation required.)
    env.setdefault("NO_NETWORK", "1")

    cmd = [
        python,
        "-m", "swebench._artifact_grade_runner",
        str(grader_dir),
        str(scratch_dir),
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GraderInvocationError(
            f"Grader timed out after {timeout_seconds}s for {task.instance_id}"
        ) from exc

    stdout = (proc.stdout or "").strip()
    if not stdout:
        raise GraderInvocationError(
            f"Grader produced no output (rc={proc.returncode}) for "
            f"{task.instance_id}. stderr:\n{proc.stderr}"
        )

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise GraderInvocationError(
            f"Grader stdout was not valid JSON for {task.instance_id}: "
            f"{stdout!r}"
        ) from exc

    if payload.get("_error"):
        raise GraderInvocationError(
            f"Grader raised {payload.get('type')} for {task.instance_id}: "
            f"{payload.get('message')}\n{payload.get('traceback', '')}"
        )

    try:
        return GradeResult.from_dict(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise GraderInvocationError(
            f"Grader output missing required fields for {task.instance_id}: "
            f"{payload!r}"
        ) from exc
