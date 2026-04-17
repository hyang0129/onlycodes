"""Unit tests for swebench.cache.

These tests avoid any real mount/unmount. ``detect_overlay_backend`` is probed
as a smoke test (it returns without raising and lands in the allowed set).
``mount_overlay`` is not exercised because it needs either CAP_SYS_ADMIN or
``fuse-overlayfs`` installed — both inappropriate for unit-test CI.
"""

from __future__ import annotations

import os
import subprocess
import sys
import venv as stdlib_venv
from pathlib import Path

import pytest

from swebench import cache


# --- cache_paths -------------------------------------------------------------


def test_cache_paths_layout(tmp_path, monkeypatch):
    """Paths are stable and composed from the instance id under CACHE_ROOT."""
    monkeypatch.setenv("SWEBENCH_CACHE_ROOT", str(tmp_path))

    paths = cache.cache_paths("django__django-16379")
    base = str(tmp_path / "instances" / "django__django-16379")
    assert paths == {
        "instance": base,
        "repo": base + "/repo",
        "venv": base + "/venv",
        "lockfile": base + "/lockfile.txt",
    }


def test_bare_repo_path_slug_sanitised(tmp_path, monkeypatch):
    monkeypatch.setenv("SWEBENCH_CACHE_ROOT", str(tmp_path))
    p = cache.bare_repo_path("django/django")
    assert p == tmp_path / "repos" / "django__django.git"


def test_has_cached_instance_requires_all_three(tmp_path, monkeypatch):
    monkeypatch.setenv("SWEBENCH_CACHE_ROOT", str(tmp_path))
    paths = cache.cache_paths("example-1")

    # Nothing → False
    assert cache.has_cached_instance("example-1") is False

    # Only repo → False
    os.makedirs(paths["repo"], exist_ok=True)
    assert cache.has_cached_instance("example-1") is False

    # repo + venv, no lockfile → False
    os.makedirs(paths["venv"], exist_ok=True)
    assert cache.has_cached_instance("example-1") is False

    # All three → True
    Path(paths["lockfile"]).write_text("requests==2.31.0\n")
    assert cache.has_cached_instance("example-1") is True


# --- scrub_cache_dir ---------------------------------------------------------


def _seed_dirty_repo(root: Path) -> None:
    """Populate root with the mix of files scrub_cache_dir should handle."""
    # Things that should be removed
    (root / "src").mkdir()
    (root / "src" / "__pycache__").mkdir()
    (root / "src" / "__pycache__" / "mod.cpython-311.pyc").write_text("x")
    (root / "src" / "mod.pyc").write_text("x")
    (root / "src" / "mod.pyo").write_text("x")
    (root / "src" / "mod.swp").write_text("x")
    (root / ".claude").mkdir()
    (root / ".claude" / "notes.md").write_text("prior context")
    (root / "pkg.egg-info").mkdir()
    (root / "pkg.egg-info" / "PKG-INFO").write_text("meta")
    (root / ".git").mkdir()
    (root / ".git" / "COMMIT_EDITMSG").write_text("wip")
    (root / ".git" / "MERGE_MSG").write_text("merge in progress")
    (root / ".git" / "FETCH_HEAD").write_text("fetched refs")

    # Things that should be preserved
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (root / ".git" / "config").write_text("[core]\n")
    (root / "src" / "real.py").write_text("print('ok')\n")
    (root / "README.md").write_text("docs\n")


def test_scrub_removes_cache_dirs_and_artifacts(tmp_path):
    _seed_dirty_repo(tmp_path)
    cache.scrub_cache_dir(str(tmp_path))

    # Removed
    assert not (tmp_path / "src" / "__pycache__").exists()
    assert not (tmp_path / "src" / "mod.pyc").exists()
    assert not (tmp_path / "src" / "mod.pyo").exists()
    assert not (tmp_path / "src" / "mod.swp").exists()
    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / "pkg.egg-info").exists()
    assert not (tmp_path / ".git" / "COMMIT_EDITMSG").exists()
    assert not (tmp_path / ".git" / "MERGE_MSG").exists()
    assert not (tmp_path / ".git" / "FETCH_HEAD").exists()

    # Preserved
    assert (tmp_path / ".git").is_dir()
    assert (tmp_path / ".git" / "HEAD").is_file()
    assert (tmp_path / ".git" / "config").is_file()
    assert (tmp_path / "src" / "real.py").is_file()
    assert (tmp_path / "README.md").is_file()


def test_scrub_on_missing_dir_is_noop(tmp_path):
    missing = tmp_path / "does-not-exist"
    cache.scrub_cache_dir(str(missing))  # must not raise


def test_scrub_is_idempotent(tmp_path):
    _seed_dirty_repo(tmp_path)
    cache.scrub_cache_dir(str(tmp_path))
    cache.scrub_cache_dir(str(tmp_path))  # second pass must also not raise
    assert (tmp_path / "README.md").is_file()


# --- lockfile ----------------------------------------------------------------


@pytest.fixture(scope="module")
def sample_venv(tmp_path_factory) -> str:
    """Build a tiny venv once and reuse it across lockfile tests.

    Installs one pinned package so there's something real in ``pip freeze``.
    """
    venv_dir = tmp_path_factory.mktemp("venv")
    stdlib_venv.create(str(venv_dir), with_pip=True)
    pip = str(venv_dir / "bin" / "pip")
    # Install a pure-Python package so we aren't at the mercy of wheels.
    # `six` is ~5KB and has zero dependencies.
    subprocess.run(
        [pip, "install", "--quiet", "six==1.16.0"],
        check=True,
        capture_output=True,
    )
    return str(venv_dir)


def test_write_and_verify_lockfile_roundtrip(sample_venv, tmp_path):
    lockfile = tmp_path / "lockfile.txt"
    cache.write_lockfile(sample_venv, str(lockfile))
    assert lockfile.is_file()
    content = lockfile.read_text()
    assert "six==1.16.0" in content
    assert cache.verify_lockfile(sample_venv, str(lockfile)) is True


def test_verify_lockfile_missing_file(sample_venv, tmp_path):
    missing = tmp_path / "nope.txt"
    assert cache.verify_lockfile(sample_venv, str(missing)) is False


def test_verify_lockfile_missing_venv(tmp_path):
    lockfile = tmp_path / "lockfile.txt"
    lockfile.write_text("six==1.16.0\n")
    missing_venv = str(tmp_path / "no-venv")
    assert cache.verify_lockfile(missing_venv, str(lockfile)) is False


def test_verify_lockfile_mismatch_returns_false(sample_venv, tmp_path):
    lockfile = tmp_path / "lockfile.txt"
    # Write a deliberately wrong lockfile.
    lockfile.write_text("six==0.0.0\n")
    assert cache.verify_lockfile(sample_venv, str(lockfile)) is False


# --- detect_overlay_backend --------------------------------------------------


def test_detect_overlay_backend_returns_known_value():
    """Smoke test: return value must be one of the known literals.

    We do not assert WHICH backend — that depends on whether the CI host has
    CAP_SYS_ADMIN or fuse-overlayfs. Either is acceptable; "none" is also
    acceptable (we just need the call to complete without raising).
    """
    backend = cache.detect_overlay_backend()
    assert backend in ("kernel", "fuse", "none")


# --- unmount_overlay idempotency --------------------------------------------


def test_unmount_overlay_on_never_mounted_path(tmp_path):
    """Calling unmount on a directory that was never mounted must not raise."""
    merged = tmp_path / "merged"
    merged.mkdir()
    # Both backends should swallow the 'not mounted' case.
    cache.unmount_overlay(str(merged), "kernel")
    cache.unmount_overlay(str(merged), "fuse")


def test_unmount_overlay_on_missing_dir_is_noop(tmp_path):
    cache.unmount_overlay(str(tmp_path / "missing"), "kernel")
