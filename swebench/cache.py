"""OverlayFS-based environment caching for SWE-bench instances.

Each instance that has been "warmed up" has a cached directory layout:

    {CACHE_ROOT}/
      repos/                        # bare clones (~12 repos)
        {owner}__{name}.git/
      instances/
        {instance_id}/
          repo/                     # checkout at base_commit, scrubbed
          venv/                     # python3.11 venv with -e . installed
          lockfile.txt              # `pip freeze` output at cache time

At run time, each evaluation mounts the cached `repo/` as the lowerdir of an
OverlayFS, hands the merged path to Claude, and `rm -rf`s the upperdir on
teardown. The venv is **not** part of the overlay — it sits as a sibling
directory because overlaying on top of a live venv introduces complexity
(site-packages perms, `.egg-info` timestamps) for no real benefit.

The module exposes stdlib-only helpers; the caller is responsible for
ordering (mount → use → unmount → cleanup) and for choosing when to invoke
`verify_lockfile` / `reinstall_editable`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal


# -- Layout ------------------------------------------------------------------

# Default cache root. Override via the SWEBENCH_CACHE_ROOT env var (used by
# tests). The env var is read on every _root() call so test fixtures that
# monkeypatch.setenv take effect without needing to re-import the module.
_DEFAULT_CACHE_ROOT = "/workspaces/.swebench-cache"


def _root() -> Path:
    """Resolve the cache root at call time, honouring SWEBENCH_CACHE_ROOT."""
    return Path(os.environ.get("SWEBENCH_CACHE_ROOT", _DEFAULT_CACHE_ROOT))


def repos_dir() -> Path:
    """Directory holding bare clones of every referenced repo."""
    return _root() / "repos"


def instances_dir() -> Path:
    """Directory holding per-instance snapshots."""
    return _root() / "instances"


def cache_paths(instance_id: str) -> dict:
    """Return the canonical paths for an instance's cache entry.

    Keys:
      - ``instance``: top-level dir (``.../instances/{id}/``)
      - ``repo``: checked-out working tree (overlay lowerdir)
      - ``venv``: python venv (outside the overlay)
      - ``lockfile``: path to the captured ``pip freeze`` output
    """
    base = instances_dir() / instance_id
    return {
        "instance": str(base),
        "repo": str(base / "repo"),
        "venv": str(base / "venv"),
        "lockfile": str(base / "lockfile.txt"),
    }


def bare_repo_path(repo_slug: str) -> Path:
    """Return the bare-clone path for a ``owner/name`` GitHub slug."""
    safe = repo_slug.replace("/", "__")
    return repos_dir() / f"{safe}.git"


def has_cached_instance(instance_id: str) -> bool:
    """True iff the instance has a complete cache entry (repo + venv + lockfile)."""
    paths = cache_paths(instance_id)
    return (
        os.path.isdir(paths["repo"])
        and os.path.isdir(paths["venv"])
        and os.path.isfile(paths["lockfile"])
    )


# -- Scrub -------------------------------------------------------------------

# Directory names (at any depth) to remove wholesale before caching.
_SCRUB_DIR_NAMES_ANY_DEPTH = {"__pycache__"}

# Directory names removed only at the repo root — intentionally narrower
# because upstream repos sometimes ship a ``.claude/`` fixture directory that
# must not be clobbered.
_SCRUB_DIR_NAMES_ROOT_ONLY = {".claude"}

# File suffixes (case-sensitive) to remove at any depth.
_SCRUB_FILE_SUFFIXES = (".pyc", ".pyo", ".swp")

# Specific files under ``.git/`` that encode local editor state; keep the rest
# of ``.git/`` intact so the working tree stays valid.
_SCRUB_GIT_FILES = ("COMMIT_EDITMSG", "MERGE_MSG", "FETCH_HEAD")


def scrub_cache_dir(repo_dir: str) -> None:
    """Remove transient artifacts before a directory is cached.

    Removes at any depth:
      - ``__pycache__/`` directories and ``*.pyc`` / ``*.pyo`` files
      - ``*.swp`` files (vim swap)
      - ``*.egg-info/`` directories (will be regenerated post-mount)
    Removes only at the repo root:
      - ``.claude/`` directory (prior-run Claude context — prevents leakage).
        Restricted to the root so upstream fixtures named ``.claude/`` deep
        in the tree are preserved.
    And specifically from ``.git/``:
      - ``COMMIT_EDITMSG``, ``MERGE_MSG``, ``FETCH_HEAD``

    The ``.git/`` directory itself is preserved so ``git status`` / ``git diff``
    keep working inside the overlay.
    """
    root = Path(repo_dir)
    if not root.is_dir():
        return

    # Walk once; collect then delete so we don't mutate during iteration.
    dirs_to_remove: list[Path] = []
    files_to_remove: list[Path] = []

    for path in root.rglob("*"):
        name = path.name
        if path.is_dir():
            if name in _SCRUB_DIR_NAMES_ANY_DEPTH:
                dirs_to_remove.append(path)
            elif name.endswith(".egg-info"):
                dirs_to_remove.append(path)
        else:
            if name.endswith(_SCRUB_FILE_SUFFIXES):
                files_to_remove.append(path)

    # Root-only directory scrubs (see _SCRUB_DIR_NAMES_ROOT_ONLY).
    for name in _SCRUB_DIR_NAMES_ROOT_ONLY:
        p = root / name
        if p.is_dir():
            dirs_to_remove.append(p)

    git_dir = root / ".git"
    if git_dir.is_dir():
        for fname in _SCRUB_GIT_FILES:
            p = git_dir / fname
            if p.is_file():
                files_to_remove.append(p)

    for d in dirs_to_remove:
        shutil.rmtree(d, ignore_errors=True)
    for f in files_to_remove:
        try:
            f.unlink()
        except FileNotFoundError:
            pass


# -- Lockfile ----------------------------------------------------------------


def _pip_freeze(venv_dir: str) -> str:
    """Return the normalised `pip freeze` output for a venv."""
    pip = os.path.join(venv_dir, "bin", "pip")
    result = subprocess.run(
        [pip, "freeze", "--disable-pip-version-check"],
        capture_output=True,
        text=True,
        check=True,
    )
    # Normalise: drop editable-install lines (their hashes/paths fluctuate)
    # and sort for deterministic comparison.
    # Also drop PEP 610 direct-URL lines (e.g. "package @ file:///path/to/repo")
    # which differ between setup time (lowerdir path) and verify time (merged path).
    lines = [
        line.rstrip()
        for line in result.stdout.splitlines()
        if line.strip()
        and not line.startswith("-e ")
        and not re.match(r"^\S+ @ (file|https?)://", line)
    ]
    lines.sort()
    return "\n".join(lines) + "\n"


def write_lockfile(venv_dir: str, lockfile_path: str) -> None:
    """Capture `pip freeze` for the venv into a lockfile on disk."""
    content = _pip_freeze(venv_dir)
    Path(lockfile_path).parent.mkdir(parents=True, exist_ok=True)
    Path(lockfile_path).write_text(content)


def verify_lockfile(venv_dir: str, lockfile_path: str) -> bool:
    """Return True iff the venv's current `pip freeze` matches the lockfile.

    Missing lockfile or missing venv returns False (callers treat this as
    "rebuild the cache").
    """
    if not os.path.isfile(lockfile_path):
        return False
    if not os.path.isdir(venv_dir):
        return False
    try:
        current = _pip_freeze(venv_dir)
    except subprocess.CalledProcessError:
        return False
    expected = Path(lockfile_path).read_text()
    return current == expected


def reinstall_editable(venv_dir: str, repo_dir: str) -> None:
    """Re-run ``pip install -e .`` to regenerate ``.egg-info`` after overlay mount.

    The scrub step removes stale ``*.egg-info/`` dirs so the cached lowerdir is
    clean. When the overlay is mounted, we need to regenerate the egg-info so
    ``import package_name`` keeps working. This writes to the upperdir, not
    the cached lowerdir.

    Raises ``OverlayError`` on non-zero pip exit — a silent failure here would
    leave the venv's egg-link pointing at a path with no egg-info, causing
    confusing ImportErrors at test time.
    """
    pip = os.path.join(venv_dir, "bin", "pip")
    result = subprocess.run(
        [pip, "install", "--quiet", "--no-deps", "-e", repo_dir],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise OverlayError(
            f"reinstall_editable failed for {repo_dir}: "
            f"{result.stderr.strip() or result.stdout.strip() or 'pip returned non-zero'}"
        )


# -- Overlay mount -----------------------------------------------------------

Backend = Literal["kernel", "fuse", "none"]


def _can_kernel_mount() -> bool:
    """Test whether ``mount -t overlay`` works in the current process.

    Uses a throwaway tmpdir so the test has zero side effects beyond the
    mount/unmount itself.
    """
    if shutil.which("mount") is None:
        return False
    tmp = tempfile.mkdtemp(prefix="overlay-probe-")
    try:
        lower = os.path.join(tmp, "lower")
        upper = os.path.join(tmp, "upper")
        work = os.path.join(tmp, "work")
        merged = os.path.join(tmp, "merged")
        for d in (lower, upper, work, merged):
            os.makedirs(d, exist_ok=True)
        result = subprocess.run(
            [
                "mount",
                "-t",
                "overlay",
                "overlay",
                "-o",
                f"lowerdir={lower},upperdir={upper},workdir={work}",
                merged,
            ],
            capture_output=True,
        )
        if result.returncode == 0:
            # Unmount before the finally's rmtree. If umount fails (rare, but
            # possible on transient EBUSY), retry with lazy unmount so the
            # tmpdir cleanup doesn't leave a dangling mount behind.
            umount_rc = subprocess.run(
                ["umount", merged], capture_output=True
            ).returncode
            if umount_rc != 0:
                subprocess.run(["umount", "-l", merged], capture_output=True)
            return True
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _can_fuse_mount() -> bool:
    """Test whether fuse-overlayfs actually works in the current process.

    Checking for the binary alone is not sufficient — seccomp filters or a
    missing /dev/fuse device node can block FUSE even when the binary is
    installed. This probes with a throwaway tmpdir mount.

    We also require ``fusermount`` to be present: without it we cannot
    unmount real FUSE mounts later, so the backend would be unusable even
    if the probe succeeds.
    """
    if shutil.which("fuse-overlayfs") is None:
        return False
    # fusermount is required to tear down real mounts; if it is absent we
    # cannot safely use the fuse backend regardless of whether the probe mount
    # succeeds.
    if shutil.which("fusermount") is None:
        return False
    tmp = tempfile.mkdtemp(prefix="fuse-probe-")
    # Track whether the probe mount is still active so the finally block
    # knows whether it is safe to rmtree tmp (walking into a live overlay
    # would corrupt the cached lowerdir).
    mount_is_active = False
    try:
        lower = os.path.join(tmp, "lower")
        upper = os.path.join(tmp, "upper")
        work = os.path.join(tmp, "work")
        merged = os.path.join(tmp, "merged")
        for d in (lower, upper, work, merged):
            os.makedirs(d, exist_ok=True)
        result = subprocess.run(
            [
                "fuse-overlayfs",
                "-o",
                f"lowerdir={lower},upperdir={upper},workdir={work}",
                merged,
            ],
            capture_output=True,
        )
        if result.returncode == 0:
            mount_is_active = True
            # Try a normal unmount first; fall back to lazy unmount (-uz).
            # Only proceed to rmtree once we are certain the mount is gone —
            # walking into a live overlay could corrupt the cached lowerdir.
            umount_rc = subprocess.run(
                ["fusermount", "-u", merged], capture_output=True
            ).returncode
            if umount_rc != 0:
                lazy_rc = subprocess.run(
                    ["fusermount", "-uz", merged], capture_output=True
                ).returncode
                if lazy_rc != 0:
                    # Neither unmount worked; leave the tmpdir in place to
                    # avoid walking into a live mount, and report failure.
                    import logging as _logging
                    _logging.getLogger(__name__).warning(
                        "_can_fuse_mount: probe mount at %s could not be "
                        "unmounted (fusermount -u and -uz both failed); "
                        "skipping rmtree to protect the filesystem.",
                        merged,
                    )
                    return False
            mount_is_active = False
            return True
        return False
    finally:
        if not mount_is_active:
            shutil.rmtree(tmp, ignore_errors=True)


def detect_overlay_backend() -> Backend:
    """Pick the best available overlay backend.

    Order of preference: kernel overlayfs (fastest, no FUSE overhead) →
    ``fuse-overlayfs`` (works without ``CAP_SYS_ADMIN``) → ``"none"``.

    Both backends are probed with a real mount attempt — binary presence alone
    is not sufficient (seccomp or a missing /dev/fuse can block FUSE even when
    the binary is installed).
    """
    if _can_kernel_mount():
        return "kernel"
    if _can_fuse_mount():
        return "fuse"
    return "none"


class OverlayError(RuntimeError):
    """Raised when overlay mount/unmount fails."""


def mount_overlay(
    lowerdir: str,
    upperdir: str,
    workdir: str,
    merged: str,
    backend: Backend,
) -> None:
    """Mount an overlay using the chosen backend.

    All four paths must exist before calling. ``backend`` must be ``"kernel"``
    or ``"fuse"`` — callers that got ``"none"`` from ``detect_overlay_backend``
    must handle that before reaching here.
    """
    for d in (lowerdir, upperdir, workdir, merged):
        os.makedirs(d, exist_ok=True)

    opts = f"lowerdir={lowerdir},upperdir={upperdir},workdir={workdir}"

    if backend == "kernel":
        cmd = ["mount", "-t", "overlay", "overlay", "-o", opts, merged]
    elif backend == "fuse":
        cmd = ["fuse-overlayfs", "-o", opts, merged]
    else:
        raise OverlayError(
            f"mount_overlay: unsupported backend {backend!r}; "
            "detect_overlay_backend returned 'none' — install "
            "fuse-overlayfs or add CAP_SYS_ADMIN."
        )

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise OverlayError(
            f"overlay mount failed (backend={backend}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )


def unmount_overlay(merged: str, backend: Backend) -> None:
    """Unmount an overlay. Safe to call on already-unmounted paths.

    Tries the backend-preferred command first; if the mount entry is gone or
    the backend binary isn't installed, swallows the error.
    """
    if not os.path.isdir(merged):
        return

    if backend == "fuse":
        binary = "fusermount"
        cmd = [binary, "-u", merged]
    else:
        # kernel — also the default if backend is unknown
        binary = "umount"
        cmd = [binary, merged]

    # If the backend binary isn't installed, there is also nothing to unmount —
    # callers get here during cleanup after the overlay was never mounted, so
    # a missing binary is equivalent to "already unmounted".
    if shutil.which(binary) is None:
        return

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return

    if result.returncode != 0:
        stderr = (result.stderr or "").lower()
        if "not mounted" in stderr or "not found" in stderr or "no such" in stderr:
            return
        # Fallback: try a lazy/forced unmount (best-effort; don't raise on
        # double-cleanup). For fuse, prefer `fusermount -uz` so we stay on
        # the canonical fuse teardown path; fall back to `umount -l` only
        # if that isn't available.
        if backend == "fuse":
            rc = subprocess.run(
                ["fusermount", "-uz", merged], capture_output=True
            ).returncode
            if rc == 0:
                return
        if shutil.which("umount") is not None:
            subprocess.run(["umount", "-l", merged], capture_output=True)
