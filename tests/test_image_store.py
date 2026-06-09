"""Tests for the image store / registry + disk policy (``swebench/image_store.py``, C3b #323).

* **Hermetic** (CI): digest resolution/manifest, size parsing, LRU prune + protect,
  pull-by-digest, rate-limit backoff, ensure_image orchestration, repo grouping —
  docker mocked.
* **``@integration``** (needs Docker): non-destructive live checks — real remote
  digest resolution, disk accounting, and idempotent pinned pull on a present image.
"""

from __future__ import annotations

import subprocess
import types
from pathlib import Path

import pytest

from swebench import container, image_store as ims


def _proc(rc=0, stdout=b"", stderr=b""):
    return types.SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)


# --------------------------------------------------------------------------
# Digest resolution + manifest
# --------------------------------------------------------------------------

_DIGEST = "sha256:" + "9b0b13a4" * 8


def test_resolve_remote_digest_ok_and_bad(monkeypatch) -> None:
    monkeypatch.setattr(container, "_docker", lambda a, **k: _proc(0, (_DIGEST + "\n").encode()))
    assert ims.resolve_remote_digest("repo:latest") == _DIGEST
    monkeypatch.setattr(container, "_docker", lambda a, **k: _proc(1, b"", b"not found"))
    with pytest.raises(container.ContainerError, match="could not resolve"):
        ims.resolve_remote_digest("repo:latest")


def test_pinned_ref() -> None:
    assert ims.pinned_ref("psf__requests-1142", _DIGEST) == (
        f"swebench/sweb.eval.x86_64.psf_1776_requests-1142@{_DIGEST}")


def test_digest_manifest_roundtrip_sorted(tmp_path, monkeypatch) -> None:
    mf = tmp_path / "digests.json"
    monkeypatch.setattr(ims, "_DIGEST_MANIFEST", mf)
    ims.record_digest("z__z-2", "sha256:bbb")
    ims.record_digest("a__a-1", "sha256:aaa")
    data = ims.load_digest_manifest()
    assert data == {"a__a-1": "sha256:aaa", "z__z-2": "sha256:bbb"}
    assert list(data) == ["a__a-1", "z__z-2"]  # persisted sorted


# --------------------------------------------------------------------------
# Sizes / cap / grouping
# --------------------------------------------------------------------------

def test_to_gb_units() -> None:
    assert round(ims._to_gb("293.2GB"), 1) == 293.2
    assert round(ims._to_gb("512MiB"), 3) == 0.537
    assert ims._to_gb("garbage") == 0.0


def test_image_disk_gb_parses_df(monkeypatch) -> None:
    monkeypatch.setattr(container, "_docker",
                        lambda a, **k: _proc(0, b"Images|293.0GB\nContainers|10GB\n"))
    assert round(ims.image_disk_gb(), 1) == 293.0


def test_min_free_gb_env(monkeypatch) -> None:
    monkeypatch.delenv("ONLYCODES_MIN_FREE_GB", raising=False)
    assert ims.min_free_gb() == ims.DEFAULT_MIN_FREE_GB
    monkeypatch.setenv("ONLYCODES_MIN_FREE_GB", "42.5")
    assert ims.min_free_gb() == 42.5
    monkeypatch.setenv("ONLYCODES_MIN_FREE_GB", "nonsense")
    assert ims.min_free_gb() == ims.DEFAULT_MIN_FREE_GB


def test_group_by_repo_version_clusters_same_repo() -> None:
    ids = ["sympy__sympy-1", "psf__requests-9", "sympy__sympy-2",
           "matplotlib__matplotlib-5", "psf__requests-1"]
    out = ims.group_by_repo_version(ids)
    # contiguous per repo, sorted by repo key, input order kept within a group.
    assert out == ["matplotlib__matplotlib-5", "psf__requests-9", "psf__requests-1",
                   "sympy__sympy-1", "sympy__sympy-2"]


# --------------------------------------------------------------------------
# Auth + pull
# --------------------------------------------------------------------------

def test_registry_login_token_and_anon(monkeypatch) -> None:
    monkeypatch.delenv("ONLYCODES_DOCKERHUB_TOKEN", raising=False)
    assert ims.registry_login() is False
    seen = {}
    monkeypatch.setenv("ONLYCODES_DOCKERHUB_TOKEN", "tok")
    monkeypatch.setenv("ONLYCODES_DOCKERHUB_USER", "alice")
    def _fake(args, **kw):
        seen["args"] = args
        seen["input"] = kw.get("input_bytes")
        return _proc(0)
    monkeypatch.setattr(container, "_docker", _fake)
    assert ims.registry_login() is True
    assert "login" in seen["args"] and "alice" in seen["args"]
    assert seen["input"] == b"tok"  # token via stdin, never argv


def test_pull_with_backoff_retries_then_succeeds(monkeypatch) -> None:
    calls = {"n": 0}
    def _fake(args, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            return _proc(1, b"", b"toomanyrequests: rate limit exceeded")
        return _proc(0)
    monkeypatch.setattr(container, "_docker", _fake)
    ims._pull_with_backoff("repo@sha256:x", retries=4, timeout=10, _sleep=lambda s: None)
    assert calls["n"] == 3


def test_pull_with_backoff_non_ratelimit_raises_immediately(monkeypatch) -> None:
    calls = {"n": 0}
    def _fake(args, **kw):
        calls["n"] += 1
        return _proc(1, b"", b"manifest unknown")
    monkeypatch.setattr(container, "_docker", _fake)
    with pytest.raises(container.ContainerError, match="manifest unknown"):
        ims._pull_with_backoff("repo@sha256:x", retries=4, timeout=10, _sleep=lambda s: None)
    assert calls["n"] == 1  # no retry for non-ratelimit errors


def test_pull_pinned_uses_manifest_digest_and_skips_present(monkeypatch) -> None:
    monkeypatch.setattr(ims, "load_digest_manifest", lambda: {"psf__requests-1142": _DIGEST})
    monkeypatch.setattr(container, "image_present", lambda ref: True)
    monkeypatch.setattr(container, "_docker", lambda a, **k: _proc(0, b"amd64\n"))  # arch lookup
    pulled = []
    monkeypatch.setattr(ims, "_pull_with_backoff", lambda ref, **k: pulled.append(ref))
    info = ims.pull_pinned("psf__requests-1142")
    assert info["digest"] == _DIGEST
    assert info["ref"].endswith(f"@{_DIGEST}")
    assert info["arch"] == "amd64"
    assert pulled == []  # already present -> no pull


# --------------------------------------------------------------------------
# Disk-full stop signal (no eviction — reuse forever)
# --------------------------------------------------------------------------

def test_pull_with_backoff_raises_diskfull_on_no_space(monkeypatch) -> None:
    monkeypatch.setattr(
        container, "_docker",
        lambda a, **k: _proc(1, b"", b"write /var/lib/docker/...: no space left on device"))
    with pytest.raises(ims.DiskFullError):
        ims._pull_with_backoff("repo@sha256:x", retries=2, timeout=1, _sleep=lambda s: None)


# --------------------------------------------------------------------------
# ensure_image — pull + keep, stop when disk is low
# --------------------------------------------------------------------------

def test_ensure_image_pulls_and_keeps(monkeypatch) -> None:
    # Plenty of free disk -> pull, never evict.
    monkeypatch.setattr(ims, "free_disk_gb", lambda: 500.0)
    monkeypatch.setattr(ims, "pull_pinned",
                        lambda iid: {"instance_id": iid, "ref": "r", "digest": _DIGEST})
    info = ims.ensure_image("psf__requests-1142")
    assert info["digest"] == _DIGEST


def test_ensure_image_raises_when_disk_low(monkeypatch) -> None:
    # Below the safety margin -> stop and ask for disk, do not pull.
    monkeypatch.setattr(ims, "free_disk_gb", lambda: 2.0)
    monkeypatch.setattr(ims, "min_free_gb", lambda: 15.0)
    monkeypatch.setattr(ims, "pull_pinned",
                        lambda iid: pytest.fail("should not pull when disk is low"))
    with pytest.raises(ims.DiskFullError):
        ims.ensure_image("psf__requests-1142")


def test_ensure_image_pulls_when_free_disk_unknown(monkeypatch) -> None:
    # free_disk_gb() == None (can't measure) -> don't block; rely on pull-failure.
    monkeypatch.setattr(ims, "free_disk_gb", lambda: None)
    monkeypatch.setattr(ims, "pull_pinned",
                        lambda iid: {"instance_id": iid, "ref": "r", "digest": _DIGEST})
    assert ims.ensure_image("psf__requests-1142")["digest"] == _DIGEST


# --------------------------------------------------------------------------
# Integration (Docker, non-destructive)
# --------------------------------------------------------------------------

def _docker_available() -> bool:
    try:
        return subprocess.run(["docker", "version"], capture_output=True, timeout=15).returncode == 0
    except Exception:
        return False


requires_docker = pytest.mark.skipif(not _docker_available(), reason="docker not available")


@pytest.mark.integration
@requires_docker
def test_resolve_digest_and_disk_live() -> None:
    ref = "swebench/sweb.eval.x86_64.psf_1776_requests-1142:latest"
    digest = ims.resolve_remote_digest(ref)
    assert digest.startswith("sha256:") and len(digest) == 71
    assert ims.image_disk_gb() > 0


@pytest.mark.integration
@requires_docker
def test_pull_pinned_idempotent_on_present_image() -> None:
    iid = "psf__requests-1142"
    ref = container.official_image_for(iid)
    if not container.image_present(ref) and not container.image_present(
            ims.pinned_ref(iid, ims.load_digest_manifest().get(iid, "sha256:0"))):
        pytest.skip("requests image not present; skip to stay non-destructive")
    info = ims.pull_pinned(iid)
    assert info["digest"].startswith("sha256:")
    assert info["ref"].endswith(f"@{info['digest']}")
