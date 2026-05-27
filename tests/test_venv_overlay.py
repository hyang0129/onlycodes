"""Tests for the per-arm venv overlay feature (--venv-isolation).

Unit tests in this file do not require real overlay mounts.
Integration tests (marked @pytest.mark.integration) need fuse-overlayfs and
a warmed-up cache entry.

All tests use a monkeypatched SWEBENCH_CACHE_ROOT so the real cache is never
touched.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import venv as stdlib_venv
from pathlib import Path
from typing import Generator

import pytest

from swebench import cache
from swebench.cache import (
    CacheError,
    OverlayError,
    cache_paths,
    has_cached_instance,
    migrate_to_isolated_layout,
    venv_overlay,
    detect_overlay_backend,
)


# ---------------------------------------------------------------------------
# Unit: layout migration
# ---------------------------------------------------------------------------


def test_migrate_legacy_to_isolated(tmp_path):
    """migrate_to_isolated_layout renames venv/ → venv_lower/."""
    instance_dir = str(tmp_path / "instance")
    os.makedirs(instance_dir)
    venv_dir = os.path.join(instance_dir, "venv")
    os.makedirs(venv_dir)
    (Path(venv_dir) / "sentinel.txt").write_text("pristine")

    migrate_to_isolated_layout(instance_dir)

    venv_lower = os.path.join(instance_dir, "venv_lower")
    assert os.path.isdir(venv_lower), "venv_lower/ must exist after migration"
    assert not os.path.isdir(venv_dir), "venv/ must be gone after migration"
    assert (Path(venv_lower) / "sentinel.txt").read_text() == "pristine"


def test_migrate_is_idempotent(tmp_path):
    """Calling migrate twice is safe; second call is a no-op."""
    instance_dir = str(tmp_path / "instance")
    os.makedirs(instance_dir)
    venv_dir = os.path.join(instance_dir, "venv")
    os.makedirs(venv_dir)

    migrate_to_isolated_layout(instance_dir)  # first call: renames
    venv_lower = os.path.join(instance_dir, "venv_lower")
    mtime_after_first = os.stat(venv_lower).st_mtime

    migrate_to_isolated_layout(instance_dir)  # second call: no-op
    mtime_after_second = os.stat(venv_lower).st_mtime
    assert mtime_after_first == mtime_after_second, "Second call must not touch venv_lower"
    assert not os.path.isdir(venv_dir), "venv/ must still be absent"


def test_migrate_noop_when_only_venv_lower(tmp_path):
    """If venv_lower/ exists and venv/ doesn't, no-op."""
    instance_dir = str(tmp_path / "instance")
    os.makedirs(instance_dir)
    venv_lower = os.path.join(instance_dir, "venv_lower")
    os.makedirs(venv_lower)
    (Path(venv_lower) / "marker.txt").write_text("ok")

    migrate_to_isolated_layout(instance_dir)  # must not raise or change anything

    assert os.path.isdir(venv_lower)
    assert (Path(venv_lower) / "marker.txt").exists()


def test_migrate_noop_when_no_venv(tmp_path):
    """If neither venv/ nor venv_lower/ exists, no-op."""
    instance_dir = str(tmp_path / "instance")
    os.makedirs(instance_dir)
    migrate_to_isolated_layout(instance_dir)  # must not raise


# ---------------------------------------------------------------------------
# Unit: has_cached_instance honours both layouts
# ---------------------------------------------------------------------------


def test_has_cached_instance_isolated_layout(tmp_path, monkeypatch):
    """With venv_isolation=True, has_cached_instance checks venv_lower/."""
    monkeypatch.setenv("SWEBENCH_CACHE_ROOT", str(tmp_path))
    paths = cache_paths("iso-test-1")

    # Nothing → False
    assert not has_cached_instance("iso-test-1", venv_isolation=True)

    # repo + lockfile, but no venv_lower → False
    os.makedirs(paths["repo"], exist_ok=True)
    Path(paths["lockfile"]).parent.mkdir(parents=True, exist_ok=True)
    Path(paths["lockfile"]).write_text("six==1.16.0\n")
    assert not has_cached_instance("iso-test-1", venv_isolation=True)

    # All three (isolated layout) → True
    os.makedirs(paths["venv_lower"], exist_ok=True)
    assert has_cached_instance("iso-test-1", venv_isolation=True) is True

    # Legacy check is False (no venv/)
    assert not has_cached_instance("iso-test-1", venv_isolation=False)


def test_has_cached_instance_legacy_layout(tmp_path, monkeypatch):
    """With venv_isolation=False, has_cached_instance checks venv/."""
    monkeypatch.setenv("SWEBENCH_CACHE_ROOT", str(tmp_path))
    paths = cache_paths("legacy-test-1")

    os.makedirs(paths["repo"], exist_ok=True)
    os.makedirs(paths["venv"], exist_ok=True)
    Path(paths["lockfile"]).parent.mkdir(parents=True, exist_ok=True)
    Path(paths["lockfile"]).write_text("six==1.16.0\n")

    assert has_cached_instance("legacy-test-1", venv_isolation=False) is True
    # Isolated check fails (no venv_lower/)
    assert not has_cached_instance("legacy-test-1", venv_isolation=True)


# ---------------------------------------------------------------------------
# Unit: venv_overlay context manager (copy fallback — no real mount needed)
# ---------------------------------------------------------------------------


def _make_fake_venv(parent: Path, name: str = "venv_lower") -> Path:
    """Create a minimal venv-like directory with a shebang script."""
    venv_dir = parent / name
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True)
    # A fake python script with a shebang baked to the original path.
    # Use str(venv_dir) directly (no f"#!/{venv_dir}" which adds a double slash).
    python_script = bin_dir / "python"
    python_script.write_text(f"#!{venv_dir}/bin/python\n# fake\n")
    python_script.chmod(0o755)
    # A site-packages marker
    sp = venv_dir / "lib" / "python3.11" / "site-packages"
    sp.mkdir(parents=True)
    (sp / "marker.txt").write_text("pristine")
    return venv_dir


def test_venv_overlay_copy_fallback_basic(tmp_path):
    """Copy fallback yields a directory with the expected contents."""
    venv_lower = _make_fake_venv(tmp_path)
    venv_merged = tmp_path / "venv"
    venv_merged.mkdir()

    with venv_overlay(
        instance_id="test-inst",
        arm="baseline",
        run_idx=1,
        venv_lower=str(venv_lower),
        venv_merged=str(venv_merged),
        upper_root=str(tmp_path / "tmp"),
        backend="none",  # force copy fallback
    ) as vdir:
        assert os.path.isdir(vdir), "Yielded directory must exist"
        sp_marker = Path(vdir) / "lib" / "python3.11" / "site-packages" / "marker.txt"
        assert sp_marker.exists(), "site-packages content must be copied"

    # After exit, copy is cleaned up
    scratch = tmp_path / "tmp" / "test-inst-baseline-run1-venv"
    assert not scratch.exists() or not (scratch / "copy").exists(), (
        "Copy fallback scratch dir must be cleaned up after context exit"
    )


def test_venv_overlay_copy_fallback_shebang_rewrite(tmp_path):
    """Shebang rewriting substitutes the old lowerdir prefix with copy_dir."""
    from swebench.cache import _rewrite_venv_shebangs

    venv_dir = tmp_path / "fake_venv"
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True)
    script = bin_dir / "pip"
    # Use str(venv_dir) directly to build the shebang so there's no double-slash.
    old_prefix = str(venv_dir)
    script.write_text(f"#!{old_prefix}/bin/python\nprint('pip')\n")
    script.chmod(0o755)

    new_venv = tmp_path / "new_venv"
    new_venv.mkdir()
    shutil.copytree(str(venv_dir / "bin"), str(new_venv / "bin"))

    new_prefix = str(new_venv)
    _rewrite_venv_shebangs(str(new_venv), old_prefix, new_prefix)

    pip_content = (new_venv / "bin" / "pip").read_text()
    assert pip_content.startswith(f"#!{new_prefix}/bin/python"), (
        f"Shebang must point to new_venv, got: {pip_content!r}"
    )


def test_venv_overlay_cleanup_on_exception(tmp_path):
    """Scratch dirs are cleaned up even when the body raises an exception."""
    venv_lower = _make_fake_venv(tmp_path)
    venv_merged = tmp_path / "venv"
    venv_merged.mkdir()

    class _Boom(RuntimeError):
        pass

    with pytest.raises(_Boom):
        with venv_overlay(
            instance_id="test-exc",
            arm="onlycode",
            run_idx=1,
            venv_lower=str(venv_lower),
            venv_merged=str(venv_merged),
            upper_root=str(tmp_path / "tmp"),
            backend="none",
        ):
            raise _Boom("injected")

    scratch = tmp_path / "tmp" / "test-exc-onlycode-run1-venv"
    assert not scratch.exists() or not (scratch / "copy").exists(), (
        "Copy fallback scratch must be cleaned up even on exception"
    )


# ---------------------------------------------------------------------------
# Regression: verify_lockfile must work when shebangs are broken
# ---------------------------------------------------------------------------


def test_verify_lockfile_works_on_renamed_venv(tmp_path):
    """verify_lockfile must succeed on venv_lower/ outside an active mount.

    Reproduces the smoke-test failure on mwaskom__seaborn-2946: cache setup
    creates the venv at venv/ (shebangs bake "<cache>/venv/bin/python"),
    captures the lockfile, then renames venv/ → venv_lower/. After the rename,
    bin/pip's shebang points at a path that doesn't exist until an arm mounts
    the overlay. Invoking pip via its shebang fails with FileNotFoundError;
    invoking it as `python -m pip` works because the interpreter binary at
    venv_lower/bin/python is still directly executable.

    Before the fix, _pip_freeze used `bin/pip` → _setup_problem_cached aborted
    Phase 1 with "setup FAILED ([Errno 2] No such file or directory:
    venv_lower/bin/pip)" on every isolation-enabled run.
    """
    from swebench.cache import verify_lockfile, write_lockfile

    canonical = tmp_path / "venv"
    stdlib_venv.create(str(canonical), with_pip=True)

    lockfile_path = str(tmp_path / "lockfile.txt")
    write_lockfile(str(canonical), lockfile_path)

    venv_lower = tmp_path / "venv_lower"
    canonical.rename(venv_lower)
    assert not canonical.exists(), "Canonical path must not exist post-rename"

    pip_script = venv_lower / "bin" / "pip"
    assert pip_script.is_file()
    first_line = pip_script.read_text().splitlines()[0]
    assert first_line.startswith(f"#!{canonical}"), (
        f"Shebang must still point at the (now missing) canonical path, got: {first_line!r}"
    )

    assert verify_lockfile(str(venv_lower), lockfile_path), (
        "verify_lockfile must return True for a freshly renamed venv whose "
        "shebangs point at a non-existent path — the python interpreter "
        "itself is still directly executable via `python -m pip`."
    )


# ---------------------------------------------------------------------------
# Integration: cache immutability under isolation
# ---------------------------------------------------------------------------


def _hash_venv_dir(venv_dir: str) -> str:
    """Return a deterministic hash of all regular files under venv_dir."""
    h = hashlib.sha256()
    for root, dirs, files in os.walk(venv_dir):
        dirs.sort()
        for fname in sorted(files):
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, venv_dir)
            h.update(rel.encode())
            try:
                h.update(Path(fpath).read_bytes())
            except OSError:
                pass
    return h.hexdigest()


@pytest.fixture
def isolated_venv_cache(tmp_path):
    """Create a real venv in venv_lower/ and a matching lockfile.

    IMPORTANT: The venv is first created at ``venv/`` (the canonical creation
    path) so that shebangs in console scripts are baked to ``<tmp>/venv/``.
    Then ``venv/`` is renamed to ``venv_lower/`` to simulate the isolated
    layout, leaving ``venv/`` free to be the overlay mountpoint.  This mirrors
    what ``cache setup`` does in production, and is why the shebang invariant
    holds: the overlay mounts ``venv_lower/`` back at ``venv/``, so
    ``#!<tmp>/venv/bin/python`` still resolves correctly.
    """
    # Step 1: create venv at the canonical path (shebangs baked to venv/).
    venv_canonical = tmp_path / "venv"
    stdlib_venv.create(str(venv_canonical), with_pip=True)
    pip = str(venv_canonical / "bin" / "pip")
    # Install a small package so the venv is non-trivial.
    subprocess.run(
        [pip, "install", "--quiet", "six==1.16.0"],
        check=True, capture_output=True,
    )
    lockfile = tmp_path / "lockfile.txt"
    lockfile.write_text("six==1.16.0\n")

    # Step 2: rename venv/ → venv_lower/ (isolated layout).
    # venv/ is now free to be the overlay mountpoint.
    venv_lower = tmp_path / "venv_lower"
    venv_canonical.rename(venv_lower)

    # Step 3: recreate venv/ as an empty dir (overlay mountpoint).
    venv_canonical.mkdir()

    return {
        "venv_lower": str(venv_lower),
        "venv_merged": str(venv_canonical),
        "lockfile": str(lockfile),
        "tmp": tmp_path,
    }


@pytest.mark.integration
def test_venv_overlay_cache_immutability(isolated_venv_cache):
    """venv_lower/ must be bit-identical before and after an arm that pip-installs."""
    fx = isolated_venv_cache
    backend = detect_overlay_backend()
    if backend == "none":
        pytest.skip("No overlay backend available (install fuse-overlayfs)")

    hash_before = _hash_venv_dir(fx["venv_lower"])

    with venv_overlay(
        instance_id="immut-test",
        arm="baseline",
        run_idx=1,
        venv_lower=fx["venv_lower"],
        venv_merged=fx["venv_merged"],
        upper_root=str(Path(fx["tmp"]) / "tmp-overlays"),
        backend=backend,
    ) as vdir:
        # Simulate an agent pip-install inside the overlay
        pip = os.path.join(vdir, "bin", "pip")
        result = subprocess.run(
            [pip, "install", "--quiet", "attrs==23.2.0"],
            capture_output=True,
        )
        assert result.returncode == 0, (
            f"pip install inside overlay failed: {result.stderr.decode()}"
        )
        # Verify the install is visible inside the overlay
        check = subprocess.run(
            [os.path.join(vdir, "bin", "python"), "-c", "import attr"],
            capture_output=True,
        )
        assert check.returncode == 0, "attrs should be importable inside the overlay"

    # After teardown, venv_lower must be unchanged
    hash_after = _hash_venv_dir(fx["venv_lower"])
    assert hash_before == hash_after, (
        "venv_lower/ was modified during arm execution — cache is NOT immutable! "
        f"hash before={hash_before!r}, after={hash_after!r}"
    )

    # And the install must NOT be visible through the lowerdir
    check_lower = subprocess.run(
        [os.path.join(fx["venv_lower"], "bin", "python"), "-c", "import attr"],
        capture_output=True,
    )
    assert check_lower.returncode != 0, (
        "attrs should NOT be importable from venv_lower after overlay teardown"
    )


@pytest.mark.integration
def test_venv_overlay_cross_arm_independence(isolated_venv_cache):
    """Arm 1's pip-install must not be visible to Arm 2."""
    fx = isolated_venv_cache
    backend = detect_overlay_backend()
    if backend == "none":
        pytest.skip("No overlay backend available (install fuse-overlayfs)")

    # Arm 1: install attrs
    with venv_overlay(
        instance_id="xarm-test",
        arm="baseline",
        run_idx=1,
        venv_lower=fx["venv_lower"],
        venv_merged=fx["venv_merged"],
        upper_root=str(Path(fx["tmp"]) / "tmp-overlays"),
        backend=backend,
    ) as vdir:
        pip = os.path.join(vdir, "bin", "pip")
        rc = subprocess.run(
            [pip, "install", "--quiet", "attrs==23.2.0"],
            capture_output=True,
        ).returncode
        assert rc == 0, "pip install in arm 1 must succeed"
        # Verify visible in arm 1
        assert subprocess.run(
            [os.path.join(vdir, "bin", "python"), "-c", "import attr"],
            capture_output=True,
        ).returncode == 0

    # Arm 2: attrs must NOT be visible (overlay was torn down and remounted fresh)
    with venv_overlay(
        instance_id="xarm-test",
        arm="onlycode",
        run_idx=1,
        venv_lower=fx["venv_lower"],
        venv_merged=fx["venv_merged"],
        upper_root=str(Path(fx["tmp"]) / "tmp-overlays"),
        backend=backend,
    ) as vdir2:
        check = subprocess.run(
            [os.path.join(vdir2, "bin", "python"), "-c", "import attr"],
            capture_output=True,
        )
        assert check.returncode != 0, (
            "attrs must NOT be importable in arm 2 — cross-arm independence violated! "
            f"(stdout={check.stdout.decode()!r}, stderr={check.stderr.decode()!r})"
        )


@pytest.mark.integration
def test_venv_overlay_backward_compat_no_isolation(tmp_path):
    """Without isolation, pip-installs in arm 1 ARE visible to arm 2 (the bug).

    This test *documents* the cross-contamination that --venv-isolation fixes.
    It does not use venv_overlay — it simulates the legacy shared-venv path
    where the venv is a shared mutable directory (no overlay, no rename).
    """
    # Legacy setup: venv lives at the canonical path as a plain directory.
    venv_dir = tmp_path / "venv"
    stdlib_venv.create(str(venv_dir), with_pip=True)

    pip = str(venv_dir / "bin" / "pip")
    python = str(venv_dir / "bin" / "python")

    # Arm 1: install attrs directly into the shared venv.
    rc = subprocess.run(
        [pip, "install", "--quiet", "attrs==23.2.0"],
        capture_output=True,
    ).returncode
    assert rc == 0, "pip install in arm 1 must succeed"

    # Arm 2: attrs IS visible (this is the documented bug).
    check = subprocess.run(
        [python, "-c", "import attr"],
        capture_output=True,
    )
    assert check.returncode == 0, (
        "With --no-venv-isolation, arm 2 SHOULD see arm 1's install "
        "(this is the documented cross-contamination bug that --venv-isolation fixes). "
        f"stdout={check.stdout.decode()!r}, stderr={check.stderr.decode()!r}"
    )
