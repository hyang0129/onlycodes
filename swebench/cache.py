"""OverlayFS-based environment caching for SWE-bench instances.

Each instance that has been "warmed up" has a cached directory layout:

    {CACHE_ROOT}/
      repos/                        # bare clones (~12 repos)
        {owner}__{name}.git/
      instances/
        {instance_id}/
          repo/                     # checkout at base_commit, scrubbed
          venv/                     # python3.11 venv (overlay mountpoint when
                                    # --venv-isolation is on; shared dir when off)
          venv_lower/               # pristine lowerdir — present only when
                                    # --venv-isolation has been used at least once
          lockfile.txt              # `pip freeze` output at cache time

At run time, each evaluation mounts the cached ``repo/`` as the lowerdir of
an OverlayFS, hands the merged path to Claude, and ``rm -rf``s the upperdir on
teardown.

With ``--venv-isolation`` (the default): the venv is also overlaid per-arm.
``venv_lower/`` is the frozen lowerdir; ``venv/`` is the fuse-overlayfs
mountpoint so agent pip-installs land in a per-arm tempdir upper layer that is
discarded after the arm.  The mounted path equals the original venv creation
path so all shebangs keep working.

Without ``--venv-isolation``: the venv sits as a shared sibling directory
(legacy behaviour, equivalent to pre-isolation runs).

The module exposes stdlib-only helpers; the caller is responsible for
ordering (mount → use → unmount → cleanup) and for choosing when to invoke
``verify_lockfile`` / ``reinstall_editable``.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Generator, Literal

_log = logging.getLogger(__name__)


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
      - ``venv``: python venv — canonical path.  With ``--venv-isolation`` this
        is the fuse-overlayfs *mountpoint*; without it, the shared venv dir.
        Shebangs in the venv always point here (the creation path).
      - ``venv_lower``: pristine lowerdir for the venv overlay.  Present only
        after a ``--venv-isolation`` run (or a lazy migration from the legacy
        layout).  Consumers should check existence before using.
      - ``lockfile``: path to the captured ``pip freeze`` output
    """
    base = instances_dir() / instance_id
    return {
        "instance": str(base),
        "repo": str(base / "repo"),
        "venv": str(base / "venv"),
        "venv_lower": str(base / "venv_lower"),
        "lockfile": str(base / "lockfile.txt"),
    }


def bare_repo_path(repo_slug: str) -> Path:
    """Return the bare-clone path for a ``owner/name`` GitHub slug."""
    safe = repo_slug.replace("/", "__")
    return repos_dir() / f"{safe}.git"


def _is_mountpoint(path: str) -> bool:
    """Return True if *path* is currently a mount point.

    Uses ``findmnt --mountpoint`` when available (Linux) — note: ``--target``
    would match any path within any mounted filesystem (always returns 0 for
    paths inside the root mount), so we must use ``--mountpoint`` which checks
    EXACTLY whether *path* is itself a mount point.

    Falls back to comparing ``os.stat()`` device numbers of *path* and its
    parent directory (different device numbers → mount point).
    """
    if shutil.which("findmnt") is not None:
        result = subprocess.run(
            ["findmnt", "--noheadings", "--mountpoint", path],
            capture_output=True,
        )
        return result.returncode == 0
    # Fallback: compare st_dev of the directory and its parent.
    try:
        st_self = os.stat(path)
        st_parent = os.stat(os.path.dirname(path) or ".")
        return st_self.st_dev != st_parent.st_dev
    except OSError:
        return False


class CacheError(RuntimeError):
    """Raised for cache-consistency violations (e.g. attempted migration of a
    live mount, or a layout that the caller cannot recover from automatically)."""


def migrate_to_isolated_layout(instance_dir: str) -> None:
    """Rename legacy ``venv/`` → ``venv_lower/`` for the isolated-venv layout.

    One-shot, idempotent: if ``venv_lower/`` already exists the function is a
    no-op.  If ``venv/`` is a live fuse mount, raises ``CacheError`` — the
    caller must tear down any active venv overlay before migrating.

    This is called lazily by callers that operate with ``--venv-isolation`` so
    existing cache entries auto-upgrade on first use without requiring a
    separate migration command.
    """
    venv = os.path.join(instance_dir, "venv")
    venv_lower = os.path.join(instance_dir, "venv_lower")
    if os.path.exists(venv_lower):
        # Already in isolated layout (or partially migrated) — nothing to do.
        return
    if not os.path.isdir(venv):
        # Nothing to rename (fresh cache entry or already fully set up).
        return
    if _is_mountpoint(venv):
        raise CacheError(
            f"{venv} is currently a fuse mount point; cannot migrate. "
            "Tear down any active venv overlay first."
        )
    os.rename(venv, venv_lower)


def has_cached_instance(instance_id: str, venv_isolation: bool = False) -> bool:
    """True iff the instance has a complete cache entry (repo + venv + lockfile).

    When *venv_isolation* is ``True`` the function checks for ``venv_lower/``
    (the isolated layout) instead of ``venv/`` (the legacy shared layout).
    Both layouts require ``repo/`` and ``lockfile.txt``.
    """
    paths = cache_paths(instance_id)
    venv_key = "venv_lower" if venv_isolation else "venv"
    return (
        os.path.isdir(paths["repo"])
        and os.path.isdir(paths[venv_key])
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

    ``--no-build-isolation`` mirrors the same flag used by the initial editable
    install in ``swebench/harness.py`` (setup_venv): the cached venv already has
    every build dep at the pinned version (setuptools, cython, numpy, etc.).
    Without this flag, PEP 517 creates a fresh build-env that pulls the LATEST
    setuptools, which has removed APIs older instances depend on (e.g.,
    ``setuptools.dep_util`` used by astropy ``setup_package.py``). (Issue #270.)

    After the pip install, ``easy-install.pth`` is pruned so it contains only
    *repo_dir*. The initial cache-build ``pip install -e`` (against the lowerdir)
    leaves the lowerdir path in ``easy-install.pth``; the subsequent install
    against the merged overlay path *appends* rather than replaces, leaving both
    entries with the lowerdir listed first. Python iterates ``.pth`` entries in
    order, so ``import <pkg>`` resolves to the unmodified lowerdir copy and the
    agent's edits in the overlay are silently masked — every test runs against
    stock code. Rewriting the file with only the merged path makes the agent's
    edits actually observable. (Issue #271.)

    Raises ``OverlayError`` on non-zero pip exit — a silent failure here would
    leave the venv's egg-link pointing at a path with no egg-info, causing
    confusing ImportErrors at test time.
    """
    pip = os.path.join(venv_dir, "bin", "pip")
    result = subprocess.run(
        [pip, "install", "--quiet", "--no-deps", "--no-build-isolation", "-e", repo_dir],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise OverlayError(
            f"reinstall_editable failed for {repo_dir}: "
            f"{result.stderr.strip() or result.stdout.strip() or 'pip returned non-zero'}"
        )

    _prune_easy_install_pth(venv_dir, repo_dir)


def _prune_easy_install_pth(venv_dir: str, repo_dir: str) -> None:
    """Rewrite ``easy-install.pth`` to contain only *repo_dir*.

    See ``reinstall_editable`` docstring for why this is required. No-op if no
    ``easy-install.pth`` exists (package wasn't installed via the legacy
    editable mechanism that writes one).
    """
    site_packages_glob = os.path.join(venv_dir, "lib", "python*", "site-packages")
    import glob as _glob

    target = os.path.realpath(repo_dir)
    for sp in _glob.glob(site_packages_glob):
        pth = os.path.join(sp, "easy-install.pth")
        if not os.path.isfile(pth):
            continue
        with open(pth, "r", encoding="utf-8") as f:
            existing = [ln.rstrip("\n") for ln in f.readlines()]
        # Keep any non-path comment/blank lines (rare in easy-install.pth);
        # replace path lines with the single canonical merged path.
        preserved = [ln for ln in existing if ln.startswith(("#", "import")) or ln.strip() == ""]
        with open(pth, "w", encoding="utf-8") as f:
            for ln in preserved:
                f.write(ln + "\n")
            f.write(target + "\n")


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
    # lowerdir must already exist (it is the cached repo snapshot).  Creating
    # it silently on a missing cache would mount an empty overlay and cause
    # mysterious test failures — raise early instead (F-19).
    if not os.path.isdir(lowerdir):
        raise OverlayError(
            f"mount_overlay: lowerdir does not exist: {lowerdir!r}. "
            "Re-run 'python -m swebench cache setup' to rebuild the cache entry."
        )
    for d in (upperdir, workdir, merged):
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


# ---------------------------------------------------------------------------
# Per-arm venv overlay
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def venv_overlay(
    *,
    instance_id: str,
    arm: str,
    run_idx: int,
    venv_lower: str,
    venv_merged: str,
    upper_root: str = "/tmp",
    backend: Backend | None = None,
) -> Generator[str, None, None]:
    """Context manager that mounts a per-arm fuse-overlayfs over the cached venv.

    On entry:
      1. Creates ``<upper_root>/<id>-<arm>-run<N>-venv/{upper,work}`` and
         ensures ``venv_merged`` exists as an empty mountpoint directory.
      2. Mounts ``fuse-overlayfs(lower=venv_lower, upper, work, merged=venv_merged)``.
      3. Yields ``venv_merged`` as the active venv directory.

    On exit (including on exception):
      4. Unmounts ``venv_merged`` via ``fusermount3 -u`` (or ``umount``).
      5. Removes the per-arm upper+work scratch dirs (best-effort).

    The canonical mount path (``venv_merged``) MUST equal the path at which the
    venv was originally created — venvs bake absolute shebangs into every
    console script (``#!/<path>/venv/bin/python``), so mounting at any other
    path breaks ``pip``, ``pytest``, etc.

    **Concurrency note:** arms of the same instance are serialised by the
    harness (parallelism is across instances, not within one).  If intra-instance
    parallelism is ever added, ``venv_merged`` would need to be per-arm and a
    shebang-relocation solution would be required.

    Failure modes:
      - If the overlay backend is unavailable (``"none"``) or the mount fails,
        the context manager falls back to a *direct copy* of ``venv_lower`` into
        a per-arm temporary directory.  Shebangs are rewritten via a sed pass
        over ``*/bin/*`` scripts.  This is the degraded path — correctness over
        performance.
      - If ``venv_merged`` is already a live mountpoint, the context manager
        attempts an unmount-and-retry once; if it remains mounted, it raises
        ``OverlayError`` (the caller should surface this, not silently skip).
      - Unmount failure on teardown is logged but does not re-raise.
    """
    if backend is None:
        backend = detect_overlay_backend()

    # Unique per-arm scratch parent under upper_root.
    scratch_parent = os.path.join(
        upper_root, f"{instance_id}-{arm}-run{run_idx}-venv"
    )
    upperdir = os.path.join(scratch_parent, "upper")
    workdir = os.path.join(scratch_parent, "work")

    # Ensure the merged mountpoint exists as an empty directory.
    os.makedirs(venv_merged, exist_ok=True)

    # If a stale overlay is sitting on the mountpoint, attempt one unmount
    # before we try to mount — this happens when a prior run crashed mid-arm.
    if _is_mountpoint(venv_merged):
        _log.warning(
            "venv_overlay: %s is already a mountpoint; attempting unmount before re-use.",
            venv_merged,
        )
        unmount_overlay(venv_merged, backend)
        if _is_mountpoint(venv_merged):
            raise OverlayError(
                f"venv_overlay: {venv_merged!r} is still mounted after unmount attempt. "
                "This is a state bug — manually run 'fusermount3 -u "
                f"{venv_merged}' and retry."
            )

    # Try the overlay mount; fall back to a copy if unavailable.
    use_copy_fallback = False
    copy_dir: str | None = None

    if backend == "none":
        use_copy_fallback = True
    else:
        os.makedirs(upperdir, exist_ok=True)
        os.makedirs(workdir, exist_ok=True)
        try:
            mount_overlay(venv_lower, upperdir, workdir, venv_merged, backend)
        except OverlayError as exc:
            _log.warning(
                "venv_overlay: fuse mount failed (%s); falling back to copy.", exc
            )
            shutil.rmtree(upperdir, ignore_errors=True)
            shutil.rmtree(workdir, ignore_errors=True)
            use_copy_fallback = True

    if use_copy_fallback:
        # Degraded path: copy the lowerdir to a per-arm tempdir and rewrite
        # shebangs in bin/ scripts so they point to the copy.
        copy_dir = os.path.join(scratch_parent, "copy")
        _log.warning(
            "venv_overlay: using copy fallback — copying %s → %s", venv_lower, copy_dir
        )
        shutil.copytree(venv_lower, copy_dir)
        # Rewrite bin/ shebangs from the original venv creation path to copy_dir.
        _rewrite_venv_shebangs(copy_dir, venv_lower, copy_dir)
        try:
            yield copy_dir
        finally:
            # Cleanup: remove the copy (best-effort) even on exception.
            shutil.rmtree(scratch_parent, ignore_errors=True)
        return

    # --- Overlay path ---
    try:
        yield venv_merged
    finally:
        # Unmount — best-effort; log on failure but do not re-raise.
        try:
            unmount_overlay(venv_merged, backend)
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "venv_overlay: unmount of %s failed (%s); "
                "marking for manual cleanup — stale mount may persist.",
                venv_merged,
                exc,
            )
        # Remove per-arm scratch dirs; leave venv_merged (the canonical path) in
        # place as an empty directory so the next arm can remount cleanly.
        shutil.rmtree(upperdir, ignore_errors=True)
        shutil.rmtree(workdir, ignore_errors=True)
        try:
            os.rmdir(scratch_parent)
        except OSError:
            pass


def _rewrite_venv_shebangs(venv_dir: str, old_prefix: str, new_prefix: str) -> None:
    """Rewrite ``#!<old_prefix>/...`` shebangs in ``<venv_dir>/bin/`` scripts.

    Used by the copy fallback path of ``venv_overlay`` when fuse-overlayfs is
    unavailable.  Only rewrites the first line of each file; binary files are
    skipped if decoding fails.

    *old_prefix* and *new_prefix* must be absolute paths without trailing slash.
    """
    bin_dir = os.path.join(venv_dir, "bin")
    if not os.path.isdir(bin_dir):
        return
    old_shebang_prefix = f"#!{old_prefix}"
    new_shebang_prefix = f"#!{new_prefix}"
    for fname in os.listdir(bin_dir):
        fpath = os.path.join(bin_dir, fname)
        if not os.path.isfile(fpath) or os.path.islink(fpath):
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                first = fh.readline()
                if not first.startswith(old_shebang_prefix):
                    continue
                rest = fh.read()
        except (UnicodeDecodeError, OSError):
            continue
        new_first = new_shebang_prefix + first[len(old_shebang_prefix):]
        try:
            with open(fpath, "w", encoding="utf-8") as fh:
                fh.write(new_first)
                fh.write(rest)
        except OSError as exc:
            _log.warning("venv_overlay: could not rewrite shebang in %s: %s", fpath, exc)
