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


def test_image_cap_gb_env(monkeypatch) -> None:
    monkeypatch.delenv("ONLYCODES_IMAGE_CAP_GB", raising=False)
    assert ims.image_cap_gb() == ims.DEFAULT_IMAGE_CAP_GB
    monkeypatch.setenv("ONLYCODES_IMAGE_CAP_GB", "42.5")
    assert ims.image_cap_gb() == 42.5
    monkeypatch.setenv("ONLYCODES_IMAGE_CAP_GB", "nonsense")
    assert ims.image_cap_gb() == ims.DEFAULT_IMAGE_CAP_GB


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
# Prune (LRU + protect)
# --------------------------------------------------------------------------

def test_prune_to_cap_evicts_lru_and_protects(monkeypatch) -> None:
    # Three distinct instances; c is oldest-used but protected, a is next LRU.
    monkeypatch.setattr(ims, "_our_images", lambda: [
        ("swebench/sweb.eval.x86_64.a_1776_a-1:latest", "id1"),   # instance a__a-1, usage 100
        ("swebench/sweb.eval.x86_64.b_1776_b-2:latest", "id2"),   # instance b__b-2, usage 999 (recent)
        ("onlycodes/prepared:c__c-3", "id3"),                     # instance c__c-3, usage 50 (protected)
    ])
    monkeypatch.setattr(ims, "_load_usage",
                        lambda: {"a__a-1": 100.0, "b__b-2": 999.0, "c__c-3": 50.0})
    # over cap through the protected-skip + the a eviction, then under.
    sizes = iter([150.0, 150.0, 150.0, 50.0, 50.0])
    monkeypatch.setattr(ims, "image_disk_gb", lambda: next(sizes))
    removed = []
    def _fake(args, **kw):
        if args[:2] == ["rmi", "-f"]:
            removed.append(args[2])
        return _proc(0)
    monkeypatch.setattr(container, "_docker", _fake)

    res = ims.prune_to_cap(100.0, protect=("c__c-3",))
    # c is the most-LRU but protected; a (next LRU) is evicted; b (recent) untouched.
    assert "swebench/sweb.eval.x86_64.a_1776_a-1:latest" in res["removed"]
    assert "onlycodes/prepared:c__c-3" not in res["removed"]
    assert "swebench/sweb.eval.x86_64.b_1776_b-2:latest" not in res["removed"]


def test_prune_to_cap_noop_when_under_cap(monkeypatch) -> None:
    monkeypatch.setattr(container, "_docker", lambda a, **k: _proc(0))
    monkeypatch.setattr(ims, "image_disk_gb", lambda: 10.0)
    res = ims.prune_to_cap(100.0)
    assert res["removed"] == []


# --------------------------------------------------------------------------
# ensure_image orchestration
# --------------------------------------------------------------------------

def test_ensure_image_stamps_prunes_and_pulls(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SWEBENCH_CACHE_ROOT", str(tmp_path))
    monkeypatch.setattr(ims, "image_disk_gb", lambda: 999.0)  # over cap
    pruned = {"called": False}
    def _fake_prune(cap, *, protect=(), _now=None):
        pruned["called"] = True
        pruned["protect"] = protect
        return {"removed": ["x"], "disk_gb_after": 10.0}
    monkeypatch.setattr(ims, "prune_to_cap", _fake_prune)
    monkeypatch.setattr(ims, "pull_pinned",
                        lambda iid: {"instance_id": iid, "ref": "r", "digest": _DIGEST})
    info = ims.ensure_image("psf__requests-1142", cap_gb=150.0, _now=1234.0)
    assert pruned["called"] and pruned["protect"] == ("psf__requests-1142",)
    assert info["pruned"] == ["x"] and info["digest"] == _DIGEST
    # usage was stamped for the instance.
    assert ims._load_usage().get("psf__requests-1142") == 1234.0


def test_ensure_image_skips_prune_under_cap(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SWEBENCH_CACHE_ROOT", str(tmp_path))
    monkeypatch.setattr(ims, "image_disk_gb", lambda: 10.0)  # under cap
    monkeypatch.setattr(ims, "prune_to_cap",
                        lambda *a, **k: pytest.fail("should not prune under cap"))
    monkeypatch.setattr(ims, "pull_pinned",
                        lambda iid: {"instance_id": iid, "ref": "r", "digest": _DIGEST})
    info = ims.ensure_image("psf__requests-1142", cap_gb=150.0, _now=1.0)
    assert info["pruned"] == []


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
