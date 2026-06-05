"""Container runtime for the Docker-image arm (epic #314 / ADR-0004, C3 #317).

Image-arm analog of :mod:`swebench.cache`'s overlay backend.  Given an instance
and its pinned official image, this module:

* **prepares a per-instance snapshot** — start a container off the official
  ``swebench/sweb.eval.*`` image, strip ``/testbed``'s git history (the
  onlycodes invariant — the agent must not recover the reference fix via
  ``git log``), then ``docker commit`` to ``onlycodes/prepared:<instance_id>``.
  Strip is paid **once** here, not per arm (C2 #316 measured ~2 s on
  matplotlib's 42k-commit history — see ``docs/spike-c2-docker-images.md``).
* **starts a fresh container per arm** from that snapshot — pristine and
  already-stripped, in ~286 ms (the per-arm reset chosen in C2).  This is the
  image-world analog of ``_refresh_overlay``.
* **moves files in/out via** ``docker cp`` — *not* bind-mounts: under
  Docker-outside-of-Docker the ``-v`` source resolves on the docker host, not
  this dev container (C2 finding).

It shells out to the ``docker`` CLI via :mod:`subprocess`, consistent with
:mod:`swebench.harness`'s git/pip wrappers (no ``docker-py`` dependency).  The
daemon is reached however ``DOCKER_HOST`` / the socket is configured —
daemon-agnostic, matching the SWE-bench harness.

Scope (C3): hand back a ready container with a stripped ``/testbed`` plus the
per-arm reset.  Registry/pull/disk-LRU is C3b (#323); agent execution is C4
(#318); test execution is C5 (#319).
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass


# --------------------------------------------------------------------------
# Errors + docker CLI wrapper
# --------------------------------------------------------------------------

class ContainerError(RuntimeError):
    """A docker CLI invocation failed, or the runtime is misconfigured."""


def _docker_bin() -> str:
    """The docker CLI to invoke. Overridable for tests via ``ONLYCODES_DOCKER``."""
    return os.environ.get("ONLYCODES_DOCKER", "docker")


def _docker(
    args: list[str],
    *,
    check: bool = True,
    timeout: float | None = None,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess:
    """Run ``docker <args>``; raise :class:`ContainerError` on non-zero unless
    ``check=False``.  Binary-safe (``capture_output`` without text decoding) so
    callers that pipe tar streams through ``docker cp -`` are not corrupted."""
    cmd = [_docker_bin(), *args]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        input=input_bytes,
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace") if proc.stderr else ""
        raise ContainerError(
            f"`docker {' '.join(args)}` failed (exit {proc.returncode}): {stderr.strip()}"
        )
    return proc


def _decode(proc: subprocess.CompletedProcess) -> str:
    out = proc.stdout
    return out.decode("utf-8", "replace").strip() if out else ""


# --------------------------------------------------------------------------
# Image / tag naming
# --------------------------------------------------------------------------

#: Token SWE-bench substitutes for the ``__`` instance-id separator in image
#: names (so ``a__b`` -> ``a_1776_b``).  Fixed upstream constant.
_NAMESPACE_TOKEN = "_1776_"


def official_image_for(instance_id: str) -> str:
    """The published SWE-bench eval image for an instance.

    ``matplotlib__matplotlib-22865`` ->
    ``swebench/sweb.eval.x86_64.matplotlib_1776_matplotlib-22865:latest``.
    """
    slug = instance_id.lower().replace("__", _NAMESPACE_TOKEN)
    return f"swebench/sweb.eval.x86_64.{slug}:latest"


def prepared_tag(instance_id: str) -> str:
    """Local tag for the stripped per-instance snapshot.

    Docker tags allow ``[A-Za-z0-9_.-]`` (<=128 chars); instance ids fit as-is.
    """
    return f"onlycodes/prepared:{instance_id}"


# --------------------------------------------------------------------------
# Handles
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class PreparedImage:
    """A per-instance snapshot whose ``/testbed`` history is already stripped."""

    instance_id: str
    base_image: str       # the official swebench image it was derived from
    snapshot_tag: str     # onlycodes/prepared:<instance_id>


@dataclass(frozen=True)
class ContainerHandle:
    """A running container started from a :class:`PreparedImage` snapshot."""

    instance_id: str
    container_id: str
    snapshot_tag: str
    testbed: str = "/testbed"


# --------------------------------------------------------------------------
# Image presence / pull (thin — registry/disk policy is C3b #323)
# --------------------------------------------------------------------------

def image_present(ref: str) -> bool:
    """True if ``ref`` is a locally available image."""
    proc = _docker(["image", "inspect", ref], check=False)
    return proc.returncode == 0


def pull_image(ref: str, *, timeout: float | None = 1800) -> None:
    """Pull ``ref`` if not already local.  A no-op when present.

    Heavy registry/disk handling (prefetch, LRU, parallelism) is C3b (#323);
    this is the minimal helper C3's prepare step and the integration test need.
    """
    if image_present(ref):
        return
    _docker(["pull", ref], timeout=timeout)


# --------------------------------------------------------------------------
# Git-history strip inside /testbed (port of harness.strip_git_history)
# --------------------------------------------------------------------------

#: Strip script run inside the container.  Mirrors the 8-step procedure in
#: ``harness.strip_git_history`` (orphan commit -> drop every other ref ->
#: delete reflog -> repack -> drop alternates -> gc --prune=now), executed via
#: ``docker exec bash``.  The image's ``/testbed`` owns its ``.git`` (no shared
#: bare repo), so the alternates step is a harmless no-op.  Author/committer
#: identity is pinned so the orphan SHA is deterministic (idempotent re-runs).
_STRIP_SCRIPT = r"""
set -eu
cd "$1"
export GIT_AUTHOR_NAME=swebench GIT_AUTHOR_EMAIL=swebench@localhost
export GIT_AUTHOR_DATE="1970-01-01T00:00:00+0000"
export GIT_COMMITTER_NAME=swebench GIT_COMMITTER_EMAIL=swebench@localhost
export GIT_COMMITTER_DATE="1970-01-01T00:00:00+0000"
TREE=$(git rev-parse HEAD^{tree})
NEW=$(git commit-tree "$TREE" -m base)
CUR=$(git symbolic-ref -q HEAD || true)
if [ -n "$CUR" ]; then
    mkdir -p "$(dirname ".git/$CUR")"
    printf '%s\n' "$NEW" > ".git/$CUR"
else
    git update-ref --no-deref HEAD "$NEW"
fi
git for-each-ref --format='%(refname)' | while IFS= read -r ref; do
    [ "$ref" = "$CUR" ] || git update-ref -d "$ref" 2>/dev/null || true
done
rm -f .git/packed-refs
rm -rf .git/logs
git repack -a -d -q
rm -f .git/objects/info/alternates
git gc --prune=now --quiet
"""


def strip_testbed(container_id: str, testbed: str = "/testbed") -> None:
    """Collapse ``testbed``'s git history to a single orphan commit, in-container.

    Post-condition (verified by ``tests/test_container_strip.py``, mirroring
    ``test_harness_strip.py``): ``git rev-list --all --count`` == 1, the orphan
    has no parents, and ``.git/logs`` / ``packed-refs`` / ``alternates`` are gone.
    """
    _docker(
        ["exec", container_id, "bash", "-c", _STRIP_SCRIPT, "strip", testbed],
        check=True,
    )


# --------------------------------------------------------------------------
# Prepare (once per instance) -> snapshot
# --------------------------------------------------------------------------

# Standard SWE-bench eval-container args: privileged-ish (unshare -n for the
# exec-server needs CAP_SYS_ADMIN — confirmed working in C2), root user, and a
# no-op foreground command so the container stays up for `docker exec`.
_RUN_ARGS = ["--cap-add=SYS_ADMIN", "--user", "root"]
_IDLE_CMD = ["tail", "-f", "/dev/null"]


def _run_detached(image: str, *, name: str | None = None) -> str:
    args = ["run", "-d", *_RUN_ARGS]
    if name:
        args += ["--name", name]
    args += [image, *_IDLE_CMD]
    return _decode(_docker(args))


def _rm_force(container_id: str) -> None:
    _docker(["rm", "-f", container_id], check=False)


def prepare_instance(
    instance_id: str,
    *,
    base_image: str | None = None,
    testbed: str = "/testbed",
    force: bool = False,
) -> PreparedImage:
    """Build (or reuse) the stripped per-instance snapshot image.

    Idempotent: if ``onlycodes/prepared:<instance_id>`` already exists and
    ``force`` is False, returns it without rebuilding.  Otherwise: ensure the
    base image is present, start a prep container, strip ``/testbed``, commit the
    snapshot, and remove the prep container.

    Strip is the only per-instance cost paid here; per-arm resets
    (:func:`start_arm_container` / :func:`reset_arm`) inherit the stripped state
    for free.
    """
    base = base_image or official_image_for(instance_id)
    tag = prepared_tag(instance_id)

    if not force and image_present(tag):
        return PreparedImage(instance_id=instance_id, base_image=base, snapshot_tag=tag)

    pull_image(base)
    prep = _run_detached(base)
    try:
        strip_testbed(prep, testbed)
        # Commit the stripped worktree as the snapshot.  --pause keeps the fs
        # quiescent during commit (the idle container writes nothing, but be
        # explicit).  The committed layer mostly *shrinks* .git (repack+gc),
        # so the snapshot adds little on top of the shared base layers.
        _docker(["commit", "--pause", prep, tag])
    finally:
        _rm_force(prep)

    return PreparedImage(instance_id=instance_id, base_image=base, snapshot_tag=tag)


# --------------------------------------------------------------------------
# Per-arm container lifecycle
# --------------------------------------------------------------------------

def start_arm_container(
    prepared: PreparedImage, *, name: str | None = None
) -> ContainerHandle:
    """Start a fresh container from the prepared snapshot.

    The container's ``/testbed`` is pristine and already history-stripped (it
    was stripped into the snapshot at prepare time).  ~286 ms in C2.
    """
    cid = _run_detached(prepared.snapshot_tag, name=name)
    return ContainerHandle(
        instance_id=prepared.instance_id,
        container_id=cid,
        snapshot_tag=prepared.snapshot_tag,
    )


def reset_arm(handle: ContainerHandle, *, name: str | None = None) -> ContainerHandle:
    """Reset between arms: discard the current container and start a fresh one
    from the same snapshot.  Returns a NEW handle (the old ``container_id`` is
    dead) — mirrors ``_refresh_overlay`` returning a refreshed handle.

    Chosen reset strategy (C3 #317, settled by C2's numbers): fresh container
    from the stripped snapshot.  Pristine by construction, no in-place reset, no
    cross-arm state leakage, no per-arm re-strip.
    """
    _rm_force(handle.container_id)
    prepared = PreparedImage(
        instance_id=handle.instance_id,
        base_image="",  # not needed for a restart; snapshot already exists
        snapshot_tag=handle.snapshot_tag,
    )
    return start_arm_container(prepared, name=name)


def teardown(handle: ContainerHandle) -> None:
    """Remove the arm container.  Best-effort; never raises."""
    _rm_force(handle.container_id)


# --------------------------------------------------------------------------
# Exec + file movement (docker cp, never bind-mounts — C2 finding)
# --------------------------------------------------------------------------

def exec_in(
    handle: ContainerHandle,
    command: list[str],
    *,
    workdir: str | None = None,
    user: str | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    """Run ``command`` inside the arm container via ``docker exec``.

    Returns the raw :class:`~subprocess.CompletedProcess` (bytes stdout/stderr)
    so callers (C4 agent invocation, C5 test execution) can stream/parse as
    needed.  ``check=False`` to inspect non-zero exits (e.g. failing tests).
    """
    args = ["exec"]
    if workdir:
        args += ["-w", workdir]
    if user:
        args += ["-u", user]
    for k, v in (env or {}).items():
        args += ["-e", f"{k}={v}"]
    args += [handle.container_id, *command]
    return _docker(args, check=check, timeout=timeout)


def copy_in(handle: ContainerHandle, src_host: str, dst_container: str) -> None:
    """Copy a host path into the container (``docker cp``).  Used instead of
    bind-mounts, which under DooD resolve on the docker host (C2 finding)."""
    _docker(["cp", src_host, f"{handle.container_id}:{dst_container}"])


def copy_out(handle: ContainerHandle, src_container: str, dst_host: str) -> None:
    """Copy a path out of the container to the host (``docker cp``).  This is how
    the agent JSONL transcript and test output reach the host."""
    _docker(["cp", f"{handle.container_id}:{src_container}", dst_host])
