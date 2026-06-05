"""Tests for the C3 container runtime (``swebench/container.py``, #317).

Two layers:

* **Hermetic** — the pure naming helpers (``official_image_for`` /
  ``prepared_tag``), no Docker required.
* **``@integration``** — the real container surface: strip ``/testbed`` git
  history inside a container (mirrors ``test_harness_strip.py``'s guarantees:
  single orphan, no reflog/packed-refs, clean tree, idempotent, detached HEAD),
  and the full ``prepare -> start -> reset -> teardown`` lifecycle.

The integration tests need a Docker daemon and one already-present SWE-bench
image; they **skip** (never pull multi-GB images in CI) when either is absent.
Override the image with ``ONLYCODES_TEST_IMAGE`` (default: the requests image,
the smallest in the published set).  They build their git repo at a throwaway
path, never touching a real ``/testbed`` snapshot, and clean up any container /
snapshot image they create.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from swebench import container
from swebench.container import (
    ContainerHandle,
    PreparedImage,
    official_image_for,
    prepared_tag,
)


# --------------------------------------------------------------------------
# Hermetic: naming helpers
# --------------------------------------------------------------------------

def test_official_image_for_maps_double_underscore_to_token() -> None:
    assert official_image_for("matplotlib__matplotlib-22865") == (
        "swebench/sweb.eval.x86_64.matplotlib_1776_matplotlib-22865:latest"
    )
    # Mixed case is lowercased (registry refs are lowercase).
    assert official_image_for("PSF__Requests-1142") == (
        "swebench/sweb.eval.x86_64.psf_1776_requests-1142:latest"
    )


def test_prepared_tag_is_local_and_carries_instance_id() -> None:
    tag = prepared_tag("django__django-10097")
    assert tag == "onlycodes/prepared:django__django-10097"
    # Repo:tag split is unambiguous and the tag part is a legal docker tag.
    repo, _, tagpart = tag.partition(":")
    assert repo == "onlycodes/prepared"
    assert len(tagpart) <= 128 and all(c.isalnum() or c in "_.-" for c in tagpart)


# --------------------------------------------------------------------------
# Integration scaffolding
# --------------------------------------------------------------------------

def _docker_available() -> bool:
    try:
        return subprocess.run(
            ["docker", "version"], capture_output=True, timeout=15
        ).returncode == 0
    except Exception:
        return False


def _test_image() -> str:
    return os.environ.get(
        "ONLYCODES_TEST_IMAGE",
        "swebench/sweb.eval.x86_64.psf_1776_requests-1142:latest",
    )


def _image_present(ref: str) -> bool:
    return container.image_present(ref)


# Docker tests are both slow/stateful (``integration`` — excluded by CI's
# ``pytest -m "not integration"``) and require a live daemon (``skipif``).
def requires_docker(fn):
    fn = pytest.mark.integration(fn)
    return pytest.mark.skipif(
        not _docker_available(), reason="docker daemon not available"
    )(fn)


@pytest.fixture()
def base_image() -> str:
    img = _test_image()
    if not _image_present(img):
        pytest.skip(f"test image not present locally: {img} (set ONLYCODES_TEST_IMAGE)")
    return img


@pytest.fixture()
def throwaway_container(base_image: str):
    """A running container off the test image; removed on teardown."""
    cid = container._run_detached(base_image)
    handle = ContainerHandle(
        instance_id="test__instance",
        container_id=cid,
        snapshot_tag=base_image,
    )
    try:
        yield handle
    finally:
        container._rm_force(cid)


# Build a multi-commit repo (3 commits on main + feature branch + tag + remote
# ref + reflog) at $1 inside the container — the container analog of
# test_harness_strip.py:_make_repo.
_MAKE_REPO = r"""
set -eu
d="$1"
rm -rf "$d"; mkdir -p "$d"; cd "$d"
git init -q -b main
git config user.email test@test; git config user.name test
echo one > a.txt; git add a.txt; git commit -q -m "commit one"
echo two > a.txt; git add a.txt; git commit -q -m "commit two -- REFERENCE FIX"
echo three > b.txt; git add b.txt; git commit -q -m "commit three"
git branch feature
git checkout -q feature; echo feat > c.txt; git add c.txt; git commit -q -m "feature work"
git checkout -q main
git tag -a v1.0 HEAD~1 -m release
git update-ref refs/remotes/origin/main "$(git rev-parse HEAD)"
"""


def _exec(handle: ContainerHandle, *cmd: str, workdir: str | None = None) -> str:
    proc = container.exec_in(handle, list(cmd), workdir=workdir, check=True)
    return proc.stdout.decode("utf-8", "replace").strip()


# --------------------------------------------------------------------------
# Integration: strip_testbed mirrors the host strip guarantees
# --------------------------------------------------------------------------

@requires_docker
def test_strip_testbed_leaves_single_orphan_clean_and_reflogless(throwaway_container):
    h = throwaway_container
    repo = "/tmp/striprepo"
    container.exec_in(h, ["bash", "-c", _MAKE_REPO, "mk", repo], check=True)

    pre_tree = _exec(h, "git", "rev-parse", "HEAD^{tree}", workdir=repo)
    container.strip_testbed(h.container_id, repo)

    # Exactly one reachable commit, with no parents.
    assert _exec(h, "git", "rev-list", "--all", "--count", workdir=repo) == "1"
    parents = _exec(h, "git", "rev-list", "--parents", "-n", "1", "HEAD", workdir=repo)
    assert len(parents.split()) == 1, f"orphan should have no parents: {parents!r}"

    # Tree (worktree content) preserved.
    assert _exec(h, "git", "rev-parse", "HEAD^{tree}", workdir=repo) == pre_tree

    # Branches/tags/remotes gone — only the current branch survives.
    refs = _exec(h, "git", "for-each-ref", "--format=%(refname)", workdir=repo)
    assert [r for r in refs.splitlines() if r.strip()] == ["refs/heads/main"]
    assert _exec(h, "git", "tag", "-l", workdir=repo) == ""

    # Reflog gone; if gc regenerated packed-refs it may only name the orphan.
    assert container.exec_in(
        h, ["test", "-d", f"{repo}/.git/logs"], check=False
    ).returncode != 0, "reflog dir must be removed"

    # Working tree clean; an agent can still commit on top of the orphan.
    assert _exec(h, "git", "status", "--porcelain", workdir=repo) == ""
    container.exec_in(h, ["bash", "-c", f"cd {repo} && echo hi > agent.txt"], check=True)
    _exec(h, "git", "add", "agent.txt", workdir=repo)
    container.exec_in(
        h,
        ["git", "-c", "user.email=a@a", "-c", "user.name=a", "commit", "-q", "-m", "agent"],
        workdir=repo,
        check=True,
    )
    assert _exec(h, "git", "rev-list", "--all", "--count", workdir=repo) == "2"


@requires_docker
def test_strip_testbed_is_idempotent(throwaway_container):
    h = throwaway_container
    repo = "/tmp/striprepo2"
    container.exec_in(h, ["bash", "-c", _MAKE_REPO, "mk", repo], check=True)

    container.strip_testbed(h.container_id, repo)
    first = _exec(h, "git", "rev-parse", "HEAD", workdir=repo)
    container.strip_testbed(h.container_id, repo)
    second = _exec(h, "git", "rev-parse", "HEAD", workdir=repo)

    assert _exec(h, "git", "rev-list", "--all", "--count", workdir=repo) == "1"
    assert first == second, "orphan SHA must be deterministic (fixed author/date)"


@requires_docker
def test_strip_testbed_handles_detached_head(throwaway_container):
    h = throwaway_container
    repo = "/tmp/striprepo3"
    container.exec_in(h, ["bash", "-c", _MAKE_REPO, "mk", repo], check=True)
    container.exec_in(h, ["git", "checkout", "-q", "HEAD~1"], workdir=repo, check=True)

    container.strip_testbed(h.container_id, repo)

    assert _exec(h, "git", "rev-list", "--all", "--count", workdir=repo) == "1"
    _exec(h, "git", "rev-parse", "HEAD", workdir=repo)  # HEAD resolves


# --------------------------------------------------------------------------
# Integration: prepare -> start -> reset -> teardown lifecycle
# --------------------------------------------------------------------------

@requires_docker
def test_prepare_start_reset_teardown_lifecycle(base_image):
    # Derive the instance id from the test image so prepare_instance resolves
    # the same base image (and a real /testbed history to strip).
    # swebench/sweb.eval.x86_64.<slug>:latest  ->  slug -> instance_id.
    slug = base_image.split("sweb.eval.x86_64.", 1)[1].rsplit(":", 1)[0]
    instance_id = slug.replace(container._NAMESPACE_TOKEN, "__")
    snapshot = prepared_tag(instance_id)

    # prepare_instance derives the snapshot tag from the instance id, so the
    # test necessarily uses the canonical tag — and its cleanup `rmi`s it. Skip
    # rather than rebuild+delete a snapshot a real run may have prepared.
    if container.image_present(snapshot):
        pytest.skip(f"would clobber an existing snapshot: {snapshot}")

    handle = None
    try:
        prepared = container.prepare_instance(instance_id, force=True)
        assert prepared.snapshot_tag == snapshot
        assert container.image_present(snapshot)

        handle = container.start_arm_container(prepared)
        # /testbed in the started container is already stripped (single orphan).
        count = _exec(
            ContainerHandle(instance_id, handle.container_id, snapshot, "/testbed"),
            "git", "rev-list", "--all", "--count", workdir="/testbed",
        )
        assert count == "1", f"/testbed should be a single orphan, got {count}"

        first_cid = handle.container_id
        handle = container.reset_arm(handle)
        assert handle.container_id != first_cid, "reset must yield a fresh container"
        # Old container is gone.
        assert container.exec_in(
            ContainerHandle(instance_id, first_cid, snapshot),
            ["true"], check=False,
        ).returncode != 0
        # Fresh container's /testbed is still a single orphan.
        assert _exec(handle, "git", "rev-list", "--all", "--count", workdir="/testbed") == "1"

        container.teardown(handle)
        assert container.exec_in(handle, ["true"], check=False).returncode != 0
        handle = None
    finally:
        if handle is not None:
            container.teardown(handle)
        # Remove the snapshot image we built so the test leaves no disk residue.
        subprocess.run(["docker", "rmi", "-f", snapshot], capture_output=True)
