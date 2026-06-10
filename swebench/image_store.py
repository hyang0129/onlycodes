"""Image acquisition + on-disk storage policy for the Verified image path (C3b #323).

The image runtime (:mod:`swebench.container`) assumes an instance image is
present locally.  This module gets it there and keeps the disk bounded:

* **Pull by digest** — resolve ``:latest`` -> digest once (``buildx imagetools
  inspect``, *no pull*), pin to ``repo@sha256:...``, and record the digest per
  instance (``swebench/data/verified_image_digests.json``) so runs are
  reproducible against an exact image, not a moving tag.
* **Auth** — anonymous Docker Hub is ~100 pulls/6 h; the 500-image set blows past
  it.  Token now (``ONLYCODES_DOCKERHUB_TOKEN``), pull-through-cache mirror later
  (the documented scale-up; see the C3b ADR note).  Pulls retry on
  ``toomanyrequests`` with backoff.
* **Disk** — measured marginal cost is ~4–6 GB per *same-repo* image (the conda
  env layer is shared only within repo+version).  **No eviction:** every image is
  kept for reuse across the whole sweep, because re-pulling against the Docker
  Hub rate limit (200/6 h) is the scarce resource, not disk — a rotating cache
  would just convert abundant disk into scarce pulls.  :func:`ensure_image` pulls
  on demand (skipping images already present) and, if the store runs out of
  space, raises :class:`DiskFullError` so the caller **stops and asks for more
  disk** rather than evicting; resume reuses everything already pulled.  Pair
  with :func:`group_by_repo_version` so a repo's shared layer is pulled once.

Shells out to the ``docker`` CLI (consistent with :mod:`swebench.container`).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

from swebench import container
from swebench.container import ContainerError, official_image_for

#: Stop and ask for more disk when free space on docker's backing store drops
#: below this margin (GB). One eval image + its prepared snapshot is ~4–6 GB;
#: keep headroom so a pull can't wedge the daemon by filling the disk mid-write.
#: Override with ``ONLYCODES_MIN_FREE_GB``.
DEFAULT_MIN_FREE_GB = 15.0

_DIGEST_MANIFEST = Path(__file__).resolve().parent / "data" / "verified_image_digests.json"


class DiskFullError(ContainerError):
    """Docker's image store is out of space (or under the safety margin).

    Raised instead of evicting: the sweep keeps every image for reuse, so the
    fix is to add disk and resume (already-pulled images are reused, no
    re-pull). See the module docstring's *Disk* note."""


def min_free_gb() -> float:
    raw = os.environ.get("ONLYCODES_MIN_FREE_GB")
    try:
        return float(raw) if raw else DEFAULT_MIN_FREE_GB
    except ValueError:
        return DEFAULT_MIN_FREE_GB


# --------------------------------------------------------------------------
# Digest manifest (committed) + remote resolution
# --------------------------------------------------------------------------

def load_digest_manifest() -> dict[str, str]:
    if _DIGEST_MANIFEST.is_file():
        try:
            return json.loads(_DIGEST_MANIFEST.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def record_digest(instance_id: str, digest: str, *, manifest_path: Path | None = None) -> None:
    """Persist ``instance_id -> digest`` into the vendored manifest (sorted)."""
    path = manifest_path or _DIGEST_MANIFEST
    data = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}
    data[instance_id] = digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(data.items())), indent=1) + "\n")


def resolve_remote_digest(ref: str) -> str:
    """Return the registry manifest digest (``sha256:...``) for ``ref`` WITHOUT
    pulling it (``docker buildx imagetools inspect``).  Used to pin a moving
    ``:latest`` to an exact image before any pull."""
    proc = container._docker(
        ["buildx", "imagetools", "inspect", ref, "--format", "{{.Manifest.Digest}}"],
        check=False,
    )
    digest = container._decode(proc) if proc.returncode == 0 else ""
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ContainerError(
            f"could not resolve remote digest for {ref!r}: "
            f"{container._decode(proc) or proc.stderr.decode('utf-8','replace')[:200]}"
        )
    return digest


def pinned_ref(instance_id: str, digest: str) -> str:
    """``repo@sha256:...`` form of an instance image, for a reproducible pull."""
    repo = official_image_for(instance_id).rsplit(":", 1)[0]
    return f"{repo}@{digest}"


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------

def registry_login() -> bool:
    """``docker login`` Docker Hub if ``ONLYCODES_DOCKERHUB_TOKEN`` (and optional
    ``ONLYCODES_DOCKERHUB_USER``) are set.  Returns True if a login was attempted
    successfully, False if no token (anonymous — fine for small runs, but
    rate-limited; see the mirror note for the full sweep)."""
    token = os.environ.get("ONLYCODES_DOCKERHUB_TOKEN")
    if not token:
        return False
    user = os.environ.get("ONLYCODES_DOCKERHUB_USER", "")
    proc = container._docker(
        ["login", "--username", user or "_", "--password-stdin"],
        check=False, input_bytes=token.encode(),
    )
    return proc.returncode == 0


# --------------------------------------------------------------------------
# Pull (by digest, rate-limit aware)
# --------------------------------------------------------------------------

def pull_pinned(
    instance_id: str,
    *,
    digest: str | None = None,
    record: bool = True,
    retries: int = 4,
    timeout: float | None = 1800,
) -> dict:
    """Ensure the instance image is present, pinned by digest.

    Resolves the digest (from ``digest``, else the committed manifest, else
    remotely) and pulls ``repo@sha256:...``.  Retries on Docker Hub
    ``toomanyrequests`` with exponential backoff.  Returns
    ``{"instance_id", "ref", "digest"}``.  When ``record``, persists a freshly
    resolved digest into the manifest.
    """
    ref_latest = official_image_for(instance_id)
    if digest is None:
        digest = load_digest_manifest().get(instance_id)
    newly_resolved = digest is None
    if digest is None:
        digest = resolve_remote_digest(ref_latest)

    ref = pinned_ref(instance_id, digest)
    if not container.image_present(ref):
        _pull_with_backoff(ref, retries=retries, timeout=timeout)
    if record and newly_resolved:
        record_digest(instance_id, digest)
    # Architecture for the run record (acceptance: digest + arch). Present after
    # pull; fall back to the x86_64 the image name encodes.
    proc = container._docker(
        ["image", "inspect", ref, "--format", "{{.Architecture}}"], check=False)
    arch = container._decode(proc) if proc.returncode == 0 else "amd64"
    return {"instance_id": instance_id, "ref": ref, "digest": digest, "arch": arch or "amd64"}


def _pull_with_backoff(ref: str, *, retries: int, timeout: float | None,
                       _sleep=time.sleep) -> None:
    delay = 30.0
    for attempt in range(1, retries + 1):
        proc = container._docker(["pull", ref], check=False, timeout=timeout)
        if proc.returncode == 0:
            return
        err = (proc.stderr or b"").decode("utf-8", "replace")
        low = err.lower()
        if "no space left on device" in low or "disk quota exceeded" in low:
            raise DiskFullError(
                f"pull {ref!r} failed: out of disk. Images are kept for reuse, "
                f"not evicted — add disk and resume. ({err.strip()[:200]})")
        if "toomanyrequests" in low or "rate limit" in low:
            if attempt < retries:
                _sleep(delay)
                delay *= 2
                continue
        raise ContainerError(f"pull {ref!r} failed: {err.strip()[:300]}")
    raise ContainerError(f"pull {ref!r} exhausted {retries} retries (rate limited)")


# --------------------------------------------------------------------------
# Disk accounting (telemetry + the out-of-space stop signal)
# --------------------------------------------------------------------------

_SIZE_RE = re.compile(r"([0-9.]+)\s*([KMGT]?i?B)", re.IGNORECASE)
_UNIT_GB = {"b": 1e-9, "kb": 1e-6, "mb": 1e-3, "gb": 1.0, "tb": 1e3,
            "kib": 2 ** 10 / 1e9, "mib": 2 ** 20 / 1e9, "gib": 2 ** 30 / 1e9,
            "tib": 2 ** 40 / 1e9}


def _to_gb(human: str) -> float:
    m = _SIZE_RE.search(human or "")
    if not m:
        return 0.0
    return float(m.group(1)) * _UNIT_GB.get(m.group(2).lower(), 1.0)


def image_disk_gb() -> float:
    """Total (dedup-aware) on-disk size of all images, in GB, per ``docker system df``."""
    proc = container._docker(["system", "df", "--format", "{{.Type}}|{{.Size}}"], check=False)
    for line in container._decode(proc).splitlines():
        kind, _, size = line.partition("|")
        if kind.strip().lower().startswith("image"):
            return _to_gb(size)
    return 0.0


def free_disk_gb(path: str | None = None) -> float | None:
    """Best-effort free space (GB) on the filesystem backing docker's image store.

    Returns ``None`` if it can't be determined.  Default target is ``/`` (under
    Docker Desktop the container's root overlay shares the daemon's backing VM
    disk, so this tracks it roughly); override with ``ONLYCODES_DOCKER_ROOT``.

    This is an **early-warning** signal only — under Docker Desktop the store
    lives in a host-side VM disk the container can't always measure accurately.
    The authoritative out-of-space signal is a failed pull (``no space left on
    device``), handled in :func:`_pull_with_backoff`.
    """
    target = path or os.environ.get("ONLYCODES_DOCKER_ROOT") or "/"
    try:
        return shutil.disk_usage(target).free / 1e9
    except OSError:
        return None


# --------------------------------------------------------------------------
# Orchestration entry for the run loop
# --------------------------------------------------------------------------

def ensure_image(instance_id: str) -> dict:
    """Make the instance image present locally (pinned by digest) and **keep it**.

    No eviction: every image is retained for reuse across the whole sweep — see
    the module docstring's *Disk* note.  :func:`pull_pinned` skips the pull when
    the image is already present.  If docker's store is out of space (or under
    the :func:`min_free_gb` safety margin), raises :class:`DiskFullError` so the
    caller stops and asks for more disk; resume reuses everything already pulled.

    This is the single entry the image-runtime arm loop calls before
    :func:`container.prepare_instance`.
    """
    free = free_disk_gb()
    if free is not None and free < min_free_gb():
        raise DiskFullError(
            f"only {free:.1f} GB free on docker's store (< {min_free_gb():.0f} GB "
            f"safety margin); images are kept for reuse, not evicted. "
            f"Add disk and resume.")
    return pull_pinned(instance_id)


# --------------------------------------------------------------------------
# Repo-grouped scheduling
# --------------------------------------------------------------------------

def _repo_version_key(instance_id: str) -> str:
    """Group key — ``<repo>`` from the instance id (``psf__requests-1142`` ->
    ``psf__requests``).  Same-repo instances share the heavy conda layer, so
    grouping them keeps re-pulls near zero under a tight cap."""
    return instance_id.rsplit("-", 1)[0]


def group_by_repo_version(instance_ids: list[str]) -> list[str]:
    """Reorder instance ids so same-repo instances are contiguous — process a
    repo's group together to reuse its shared layer before eviction.  Stable
    within a group (preserves input order)."""
    groups: dict[str, list[str]] = {}
    for iid in instance_ids:
        groups.setdefault(_repo_version_key(iid), []).append(iid)
    out: list[str] = []
    for key in sorted(groups):
        out.extend(groups[key])
    return out
