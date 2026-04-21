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
# Cap on how much of the generator's stderr we embed into MaterializationError
# messages. A runaway generator can produce hundreds of MB before the 180s
# timeout fires; without a cap the exception message itself could OOM logs.
_GENERATOR_STDERR_MAX_CHARS = 8 * 1024


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
    # Use the stripped, normalised value from _resolve_generator_rel — NOT the
    # raw attribute — so leading/trailing whitespace in the yaml does not leak
    # into the constructed path (F-1).
    generator_abs = (task.task_dir / generator_rel) if generator_rel else None

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
        # stdout is discarded (generators should be quiet); stderr is captured
        # but truncated before being embedded in any exception message.
        result = subprocess.run(
            cmd,
            cwd=str(scratch_dir),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
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
        stderr_tail = _truncate_for_error(result.stderr or "")
        raise MaterializationError(
            f"workspace_generator for {task.instance_id!r} failed with "
            f"exit={result.returncode}\nstderr (last "
            f"{_GENERATOR_STDERR_MAX_CHARS} chars):\n{stderr_tail}"
        )

    marker.write_text("ok\n")


def _truncate_for_error(text: str) -> str:
    """Keep the last ``_GENERATOR_STDERR_MAX_CHARS`` chars of ``text``.

    Generator failures almost always surface at the tail of stderr, so keep
    the tail rather than the head.
    """
    if len(text) <= _GENERATOR_STDERR_MAX_CHARS:
        return text
    return "…(truncated)…\n" + text[-_GENERATOR_STDERR_MAX_CHARS:]


def _seed_for_instance(instance_id: str) -> int:
    """Derive a stable 32-bit seed from the instance_id (hash-salt free)."""
    digest = hashlib.sha256(instance_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _assert_no_leak(scratch_dir: Path, generator_abs: Path | None = None) -> None:
    """Fail loudly if any grader artifact or the generator script leaked into scratch.

    The generator check is keyed on the *relative path* the generator would
    occupy under scratch (mirroring its path under ``workspace/``), not on
    basename. This matches the ignore callable in :func:`_make_ignore_for_generator`,
    so a hand-curated helper that happens to share the generator's basename but
    lives at a different path inside ``workspace/`` is NOT flagged.
    """
    # "hidden.py" is the grader's module filename; reference_output.* is the
    # golden artifact. Either appearing inside the scratch dir is a bug.
    leaks: list[Path] = []
    # Compute the exact path inside scratch that the generator would occupy if
    # it leaked. For ``workspace/generator.py`` this is ``scratch/generator.py``;
    # for ``workspace/sub/g.py`` this is ``scratch/sub/g.py``.
    generator_scratch_path: Path | None = None
    if generator_abs is not None:
        # generator_abs lives under workspace/; find its path relative to that
        # workspace dir so we can project it onto scratch_dir.
        try:
            ws_root = generator_abs
            # Walk up until we find the directory that was the root of the copy.
            # We don't have the workspace_src here, so use the parent chain of
            # the generator's resolved path until it stops being a descendant.
            # Simpler: use just the basename-under-its-own-dir, anchored at
            # scratch_dir. Since the copy preserves structure, the relative
            # path from workspace/ to the generator equals the relative path
            # from scratch_dir/ to where the generator would land.
            workspace_src = generator_abs.parent
            while workspace_src.name != "workspace" and workspace_src.parent != workspace_src:
                workspace_src = workspace_src.parent
            rel = generator_abs.relative_to(workspace_src)
            generator_scratch_path = (scratch_dir / rel).resolve()
        except ValueError:
            # Fallback: if we cannot compute a relative path, fall back to
            # basename matching anchored at scratch root only (NOT recursive).
            generator_scratch_path = (scratch_dir / generator_abs.name).resolve()

    for path in scratch_dir.rglob("*"):
        if not path.is_file():
            continue
        name = path.name
        if name == "hidden.py":
            leaks.append(path)
        elif name.startswith("reference_output"):
            leaks.append(path)
        elif (
            generator_scratch_path is not None
            and path.resolve() == generator_scratch_path
        ):
            leaks.append(path)
    if leaks:
        rels = [str(p.relative_to(scratch_dir)) for p in leaks]
        raise MaterializationError(
            f"No-leak invariant violated in {scratch_dir}: {rels}"
        )


# Backward-compat alias for any external callers of the old private helper.
_assert_no_grader_leak = _assert_no_leak
