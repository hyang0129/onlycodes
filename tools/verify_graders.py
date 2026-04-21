#!/usr/bin/env python3
"""Pre-merge grader sanity gate.

Walks ``problems/artifact/<category>/<slug>/task.yaml``, copies each task's
``reference_output`` into a temp scratch dir as the expected output artifact,
invokes the harness grader, and reports PASS/FAIL per task.

Exit codes:
  0  all graders returned passed=True
  1  at least one grader returned passed=False or raised GraderInvocationError
  2  discovery/parse error (missing task.yaml fields, loader ValueError)
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

# Allow running as ``python tools/verify_graders.py`` from the repo root
# without editable-installing swebench.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from swebench.artifact_grade import GraderInvocationError, invoke_grader
from swebench.artifact_loader import load_tasks
from swebench.artifact_materialize import materialize


def _verify_task(task) -> tuple[str, str]:
    """Run one task's grader against its reference_output.

    Returns (status, detail) where status is "PASS", "FAIL", or "ERROR".
    """
    if task.task_dir is None:
        return "ERROR", "task_dir not set"

    ref_path = task.task_dir / task.reference_output
    if not ref_path.is_file():
        return "ERROR", f"reference_output not found: {ref_path}"

    with tempfile.TemporaryDirectory(prefix="verify_graders_") as tmp:
        scratch = Path(tmp) / "scratch"
        # Materialize workspace so the grader can access input files, then
        # place the reference output where the grader expects the agent artifact.
        try:
            materialize(task, scratch)
        except Exception as exc:
            return "ERROR", f"workspace materialization failed: {exc}"

        dest = scratch / task.output_artifact
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ref_path, dest)

        try:
            result = invoke_grader(task, scratch)
        except GraderInvocationError as exc:
            return "ERROR", str(exc)

    if result.passed:
        return "PASS", result.detail
    return "FAIL", result.detail


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tasks-dir",
        type=Path,
        default=_REPO_ROOT / "problems" / "artifact",
        help="Root tasks directory (default: <repo>/problems/artifact/)",
    )
    args = parser.parse_args(argv)
    tasks_dir: Path = args.tasks_dir

    try:
        tasks = load_tasks(tasks_dir)
    except ValueError as exc:
        print(f"ERROR: task discovery/parse failed: {exc}", file=sys.stderr)
        return 2

    if not tasks:
        print("No tasks found — nothing to verify.", file=sys.stderr)
        return 2

    overall_exit = 0
    for task in tasks:
        status, detail = _verify_task(task)
        print(f"{status:5s}  {task.instance_id}  {detail}")
        if status != "PASS":
            overall_exit = 1

    return overall_exit


if __name__ == "__main__":
    sys.exit(main())
