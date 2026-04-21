"""Workspace materialization for artifact-graded benchmark tasks.

ABSOLUTE invariant (see SCHEMA §5 and refined spec Q3): the agent's scratch
dir contains ONLY the contents of ``workspace/`` (plus whatever the agent
writes at run time). ``grader/`` and ``reference_output.*`` MUST NEVER be
copied in. A post-copy scan enforces this invariant.

Optional generator (issue #118): a task may declare
``workspace_generator: <path>`` in ``task.yaml`` pointing at a Python script
under ``workspace/``. The script is NOT copied into scratch; instead it is
invoked as a subprocess after the copytree, and writes the bulk data files
directly into ``scratch_dir``. This keeps large generated datasets out of
the git history while preserving byte-stable, seeded materialization.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

from swebench.artifact_models import Task

_GENERATOR_MARKER = ".workspace_generator_done"
_GENERATOR_TIMEOUT_S = 180


class MaterializationError(RuntimeError):
    """Raised when the no-leak invariant is violated or the generator fails."""


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
    - When ``task.workspace_generator`` is set, the declared generator file is
      excluded from the copy, then invoked as a subprocess to populate the
      bulk data files into ``scratch_dir``.
    - Raises ``MaterializationError`` if a post-copy scan finds a grader leak
      or if the generator subprocess fails.

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

    generator_rel = _resolve_generator_rel(task)
    generator_abs = task.task_dir / task.workspace_generator if generator_rel else None

    if generator_abs is not None and not generator_abs.is_file():
        raise FileNotFoundError(
            f"workspace_generator not found: {generator_abs}"
        )

    ignore = _make_ignore_for_generator(workspace_src, generator_abs) if generator_abs else None

    # We only copy workspace/. grader/ is left behind by construction.
    shutil.copytree(
        workspace_src,
        scratch_dir,
        dirs_exist_ok=True,
        symlinks=False,
        ignore=ignore,
    )

    if generator_abs is not None:
        _run_generator(task, generator_abs, scratch_dir)

    _assert_no_leak(scratch_dir, generator_abs)
    return scratch_dir


def _resolve_generator_rel(task: Task) -> str | None:
    """Return the declared generator path, normalised, or ``None``."""
    raw = task.workspace_generator
    if raw is None:
        return None
    raw = raw.strip()
    return raw or None


def _make_ignore_for_generator(
    workspace_src: Path,
    generator_abs: Path,
):
    """Build a ``shutil.copytree`` ignore callable that excludes the generator file.

    Only files whose absolute path equals ``generator_abs`` are excluded. This
    is intentionally path-based (not name-based) to avoid false positives if
    another file happens to share the generator's filename.
    """
    workspace_src = workspace_src.resolve()
    generator_abs = generator_abs.resolve()

    def _ignore(src_dir: str, names: list[str]) -> list[str]:
        src_path = Path(src_dir).resolve()
        dropped: list[str] = []
        for name in names:
            if (src_path / name).resolve() == generator_abs:
                dropped.append(name)
        return dropped

    return _ignore


def _run_generator(task: Task, generator_abs: Path, scratch_dir: Path) -> None:
    """Invoke ``generator_abs`` as a subprocess, writing into ``scratch_dir``.

    Idempotent: if the marker file ``.workspace_generator_done`` exists in
    ``scratch_dir`` a second call is a no-op. The marker is written after a
    successful run; on failure the marker is absent and a retry will re-run.
    """
    marker = scratch_dir / _GENERATOR_MARKER
    if marker.exists():
        return

    seed = _seed_for_instance(task.instance_id)

    # Scrubbed env: pass only PATH so the generator can find its interpreter,
    # and set PYTHONDONTWRITEBYTECODE so we don't leave __pycache__ in scratch.
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    cmd = [
        sys.executable,
        str(generator_abs),
        "--seed", str(seed),
        "--output-dir", str(scratch_dir),
        "--instance-id", task.instance_id,
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(scratch_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=_GENERATOR_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MaterializationError(
            f"workspace_generator for {task.instance_id!r} timed out after "
            f"{_GENERATOR_TIMEOUT_S}s: {exc}"
        ) from None

    if result.returncode != 0:
        raise MaterializationError(
            f"workspace_generator for {task.instance_id!r} failed with "
            f"exit={result.returncode}\nstdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

    marker.write_text("ok\n")


def _seed_for_instance(instance_id: str) -> int:
    """Derive a stable 32-bit seed from the instance_id (hash-salt free)."""
    digest = hashlib.sha256(instance_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _assert_no_leak(scratch_dir: Path, generator_abs: Path | None) -> None:
    """Fail loudly if any grader artifact or the generator script leaked into scratch."""
    # "hidden.py" is the grader's module filename; reference_output.* is the
    # golden artifact. Either appearing inside the scratch dir is a bug.
    leaks: list[Path] = []
    generator_name = generator_abs.name if generator_abs is not None else None
    for path in scratch_dir.rglob("*"):
        if not path.is_file():
            continue
        name = path.name
        if name == "hidden.py":
            leaks.append(path)
        elif name.startswith("reference_output"):
            leaks.append(path)
        elif generator_name is not None and name == generator_name:
            leaks.append(path)
    if leaks:
        rels = [str(p.relative_to(scratch_dir)) for p in leaks]
        raise MaterializationError(
            f"No-leak invariant violated in {scratch_dir}: {rels}"
        )


# Backward-compat alias for any external callers of the old private helper.
_assert_no_grader_leak = _assert_no_leak
