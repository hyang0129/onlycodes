"""Integration tests for the OverlayFS cache layer.

These tests exercise the full cache lifecycle against a real network clone and a
real overlay mount. They are slow (~2–5 min for the first run) and require:
  - Network access (to clone django/django from GitHub)
  - fuse-overlayfs installed (for the mount tests)

Run with:
    pytest tests/test_cache_integration.py -v -m integration

The cache is written to SWEBENCH_CACHE_ROOT (default: /tmp/swebench-integ-cache)
and persists across runs so subsequent runs skip the clone+venv setup.
"""

from __future__ import annotations

import glob
import os
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

INSTANCE_ID = "django__django-11815"
BASE_COMMIT = "e02f67ef2d03d48128e7a118bf75f0418e24e8ac"

# Persistent cache dir — avoids re-cloning on every test session.
CACHE_DIR = Path(
    os.environ.get("SWEBENCH_CACHE_ROOT", "/tmp/swebench-integ-cache")
)

WORK_DIR = Path("/workspaces/hub_1/onlycodes-issue-11")


def _instance_yaml_exists() -> bool:
    return bool(glob.glob(f"problems/**/{INSTANCE_ID}.yaml", recursive=True))


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _instance_yaml_exists(),
        reason=f"Problem YAML for {INSTANCE_ID} not found in problems/",
    ),
]


# ---------------------------------------------------------------------------
# Session fixture — set SWEBENCH_CACHE_ROOT once for all tests + subprocesses
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def pin_cache_root():
    """Override SWEBENCH_CACHE_ROOT for the whole test session.

    Sets os.environ directly so both in-process imports and subprocess calls
    see the same path.
    """
    original = os.environ.get("SWEBENCH_CACHE_ROOT")
    os.environ["SWEBENCH_CACHE_ROOT"] = str(CACHE_DIR)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    yield
    if original is None:
        os.environ.pop("SWEBENCH_CACHE_ROOT", None)
    else:
        os.environ["SWEBENCH_CACHE_ROOT"] = original


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "swebench", *args],
        capture_output=True,
        text=True,
        cwd=str(WORK_DIR),
        env=os.environ,
    )


def _cache():
    """Fresh import of swebench.cache with SWEBENCH_CACHE_ROOT already set."""
    from swebench import cache
    return cache


# ---------------------------------------------------------------------------
# Phase 1 — cache setup
# ---------------------------------------------------------------------------

class TestCacheSetup:
    def test_setup_creates_instance_directory(self):
        result = _run_cli(
            "cache", "setup",
            "--filter", INSTANCE_ID,
            "--concurrency", "1",
        )
        assert result.returncode == 0, (
            f"cache setup failed.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_repo_directory_exists(self):
        repo = CACHE_DIR / "instances" / INSTANCE_ID / "repo"
        assert repo.is_dir(), f"Expected {repo} to exist"

    def test_venv_directory_exists(self):
        venv = CACHE_DIR / "instances" / INSTANCE_ID / "venv"
        assert venv.is_dir()

    def test_lockfile_exists_and_non_empty(self):
        lockfile = CACHE_DIR / "instances" / INSTANCE_ID / "lockfile.txt"
        assert lockfile.is_file()
        assert lockfile.stat().st_size > 0

    def test_repo_is_at_base_commit(self):
        repo = CACHE_DIR / "instances" / INSTANCE_ID / "repo"
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=str(repo),
        )
        assert result.returncode == 0
        assert result.stdout.strip() == BASE_COMMIT

    def test_repo_has_no_pycache(self):
        repo = CACHE_DIR / "instances" / INSTANCE_ID / "repo"
        pycaches = list(repo.rglob("__pycache__"))
        assert pycaches == [], f"Found __pycache__ dirs: {pycaches}"

    def test_repo_has_no_dot_claude(self):
        repo = CACHE_DIR / "instances" / INSTANCE_ID / "repo"
        assert not (repo / ".claude").exists()

    def test_setup_is_idempotent(self):
        """Second run must report 'already cached' without error."""
        result = _run_cli(
            "cache", "setup",
            "--filter", INSTANCE_ID,
            "--concurrency", "1",
        )
        assert result.returncode == 0, result.stderr
        assert "already cached" in result.stdout

    def test_has_cached_instance_returns_true(self):
        cache = _cache()
        assert cache.has_cached_instance(INSTANCE_ID) is True

    def test_lockfile_verifies_clean(self):
        cache = _cache()
        paths = cache.cache_paths(INSTANCE_ID)
        assert cache.verify_lockfile(paths["venv"], paths["lockfile"]) is True


# ---------------------------------------------------------------------------
# Phase 2 — overlay mount / teardown
# ---------------------------------------------------------------------------

def _skip_if_no_overlay():
    cache = _cache()
    return cache.detect_overlay_backend() == "none"


@pytest.mark.skipif(
    _skip_if_no_overlay(),
    reason="No overlay backend available (install fuse-overlayfs or add CAP_SYS_ADMIN)",
)
class TestOverlayMountTeardown:
    def test_mount_creates_visible_lowerdir_files(self, tmp_path):
        cache = _cache()
        backend = cache.detect_overlay_backend()
        paths = cache.cache_paths(INSTANCE_ID)
        lower = paths["repo"]

        upper = str(tmp_path / "upper")
        work = str(tmp_path / "work")
        merged = str(tmp_path / "merged")
        for d in (upper, work, merged):
            Path(d).mkdir(parents=True)

        cache.mount_overlay(lower, upper, work, merged, backend)
        try:
            assert any(Path(merged).iterdir()), "Merged dir is empty after mount"
            sentinel = Path(merged) / "__integration_sentinel__.txt"
            sentinel.write_text("hello")
            assert not (Path(lower) / "__integration_sentinel__.txt").exists()
            assert (Path(upper) / "__integration_sentinel__.txt").exists()
        finally:
            cache.unmount_overlay(merged, backend)

    def test_teardown_removes_all_overlay_dirs(self, tmp_path):
        cache = _cache()
        from swebench.run import _OverlayHandle, _teardown_overlay

        backend = cache.detect_overlay_backend()
        paths = cache.cache_paths(INSTANCE_ID)
        lower = paths["repo"]

        upper = str(tmp_path / "upper")
        work = str(tmp_path / "work")
        merged = str(tmp_path / "merged")
        for d in (upper, work, merged):
            Path(d).mkdir(parents=True)

        cache.mount_overlay(lower, upper, work, merged, backend)

        handle = _OverlayHandle(
            merged=merged, upperdir=upper, workdir=work, backend=backend
        )
        _teardown_overlay(handle)

        assert not Path(merged).exists(), "merged dir survived teardown"
        assert not Path(upper).exists(), "upperdir survived teardown"
        assert not Path(work).exists(), "workdir survived teardown"

    def test_no_dangling_mounts_after_teardown(self, tmp_path):
        cache = _cache()
        from swebench.run import _OverlayHandle, _teardown_overlay

        backend = cache.detect_overlay_backend()
        paths = cache.cache_paths(INSTANCE_ID)
        lower = paths["repo"]

        upper = str(tmp_path / "upper")
        work = str(tmp_path / "work")
        merged = str(tmp_path / "merged")
        for d in (upper, work, merged):
            Path(d).mkdir(parents=True)

        cache.mount_overlay(lower, upper, work, merged, backend)
        handle = _OverlayHandle(
            merged=merged, upperdir=upper, workdir=work, backend=backend
        )
        _teardown_overlay(handle)

        mounts = subprocess.run(["mount"], capture_output=True, text=True).stdout
        assert merged not in mounts, f"Stale mount found for {merged}"


# ---------------------------------------------------------------------------
# Phase 3 — lockfile drift triggers rebuild
# ---------------------------------------------------------------------------

class TestLockfileDrift:
    def test_drift_detected_and_rebuilt(self):
        cache = _cache()
        paths = cache.cache_paths(INSTANCE_ID)
        lockfile_path = Path(paths["lockfile"])
        original = lockfile_path.read_text()

        lockfile_path.write_text(original + "fakepkg==99.0.0\n")
        assert not cache.verify_lockfile(paths["venv"], paths["lockfile"])

        result = _run_cli(
            "cache", "setup",
            "--filter", INSTANCE_ID,
            "--concurrency", "1",
            "--force",
        )
        assert result.returncode == 0, result.stderr

        assert cache.verify_lockfile(paths["venv"], paths["lockfile"]), (
            "Lockfile still mismatched after --force rebuild"
        )

    def test_lockfile_does_not_contain_editable_installs(self):
        cache = _cache()
        paths = cache.cache_paths(INSTANCE_ID)
        content = Path(paths["lockfile"]).read_text()
        editable_lines = [l for l in content.splitlines() if l.startswith("-e ")]
        assert editable_lines == [], f"Found editable lines in lockfile: {editable_lines}"
