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
  env layer is shared only within repo+version), so the full set is hundreds of
  GB → ~1 TB and **can't be held at once**.  :func:`ensure_image` pulls on demand
  and :func:`prune_to_cap` LRU-evicts to a cap (default 150 GB).  Pair with
  :func:`group_by_repo_version` so a repo's shared layer is reused before it's
  evicted.

Shells out to the ``docker`` CLI (consistent with :mod:`swebench.container`).
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from swebench import container
from swebench.container import ContainerError, official_image_for

#: Default on-disk cap for the image store. Tight on purpose (holds one–two
#: repo-groups hot), forcing repo-grouped scheduling. Override with
#: ``ONLYCODES_IMAGE_CAP_GB``.
DEFAULT_IMAGE_CAP_GB = 150.0

_DIGEST_MANIFEST = Path(__file__).resolve().parent / "data" / "verified_image_digests.json"


def image_cap_gb() -> float:
    raw = os.environ.get("ONLYCODES_IMAGE_CAP_GB")
    try:
        return float(raw) if raw else DEFAULT_IMAGE_CAP_GB
    except ValueError:
        return DEFAULT_IMAGE_CAP_GB


# --------------------------------------------------------------------------
# Usage log (for LRU) — runtime cache, not committed
# --------------------------------------------------------------------------

def _usage_path() -> Path:
    root = os.environ.get("SWEBENCH_CACHE_ROOT", "/workspaces/.swebench-cache")
    return Path(root) / "image_usage.json"


def _load_usage() -> dict[str, float]:
    p = _usage_path()
    if p.is_file():
        try:
            return json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _stamp_usage(instance_id: str, *, now: float) -> None:
    p = _usage_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    usage = _load_usage()
    usage[instance_id] = now
    p.write_text(json.dumps(usage))


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
    return {"instance_id": instance_id, "ref": ref, "digest": digest}


def _pull_with_backoff(ref: str, *, retries: int, timeout: float | None,
                       _sleep=time.sleep) -> None:
    delay = 30.0
    for attempt in range(1, retries + 1):
        proc = container._docker(["pull", ref], check=False, timeout=timeout)
        if proc.returncode == 0:
            return
        err = (proc.stderr or b"").decode("utf-8", "replace")
        if "toomanyrequests" in err.lower() or "rate limit" in err.lower():
            if attempt < retries:
                _sleep(delay)
                delay *= 2
                continue
        raise ContainerError(f"pull {ref!r} failed: {err.strip()[:300]}")
    raise ContainerError(f"pull {ref!r} exhausted {retries} retries (rate limited)")


# --------------------------------------------------------------------------
# Disk accounting + prune (LRU)
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


def _our_images() -> list[tuple[str, str]]:
    """(repository, image_id) for swebench eval images + our prepared snapshots."""
    proc = container._docker(
        ["images", "--format", "{{.Repository}}|{{.ID}}", "--no-trunc"], check=False)
    out = []
    for line in container._decode(proc).splitlines():
        repo, _, iid = line.partition("|")
        if "sweb.eval" in repo or repo.startswith("onlycodes/prepared"):
            out.append((repo, iid))
    return out


def _instance_of_repo(repo: str) -> str | None:
    if repo.startswith("onlycodes/prepared:"):
        return repo.split(":", 1)[1]
    m = re.search(r"sweb\.eval\.x86_64\.(.+)", repo)
    if m:
        return m.group(1).rsplit(":", 1)[0].replace(container._NAMESPACE_TOKEN, "__")
    return None


def prune_to_cap(cap_gb: float, *, protect: tuple[str, ...] = (), _now=None) -> dict:
    """Evict images LRU until image disk is under ``cap_gb``.

    Order: dangling images + stopped containers first (free reclaimable space —
    the daemon routinely carries tens of GB here), then our images (prepared
    snapshots and base eval images) by least-recently-used instance, skipping any
    instance in ``protect``.  Returns ``{"removed": [...], "disk_gb_after": ...}``.
    """
    removed: list[str] = []
    # Cheap reclaim first: stopped containers + dangling images.
    container._docker(["container", "prune", "-f"], check=False)
    container._docker(["image", "prune", "-f"], check=False)
    if image_disk_gb() <= cap_gb:
        return {"removed": removed, "disk_gb_after": image_disk_gb()}

    usage = _load_usage()
    protect_set = set(protect)
    # LRU order: oldest-used (or never-used = -inf) first.
    images = _our_images()

    def _key(item: tuple[str, str]) -> float:
        inst = _instance_of_repo(item[0])
        return usage.get(inst, float("-inf")) if inst else float("-inf")

    for repo, _iid in sorted(images, key=_key):
        if image_disk_gb() <= cap_gb:
            break
        inst = _instance_of_repo(repo)
        if inst and inst in protect_set:
            continue
        if container._docker(["rmi", "-f", repo], check=False).returncode == 0:
            removed.append(repo)
    return {"removed": removed, "disk_gb_after": image_disk_gb()}


# --------------------------------------------------------------------------
# Orchestration entry for the run loop
# --------------------------------------------------------------------------

def ensure_image(instance_id: str, *, cap_gb: float | None = None, _now=None) -> dict:
    """Make the instance image present (pinned by digest), keeping disk under the
    cap.  Stamps LRU usage, prunes if over cap (protecting this instance), then
    pulls.  Returns :func:`pull_pinned`'s dict plus ``"pruned"``.

    This is the single entry the image-runtime arm loop calls before
    :func:`container.prepare_instance`.
    """
    cap = cap_gb if cap_gb is not None else image_cap_gb()
    now = _now if _now is not None else time.time()
    _stamp_usage(instance_id, now=now)

    pruned: dict = {"removed": []}
    if image_disk_gb() > cap:
        pruned = prune_to_cap(cap, protect=(instance_id,), _now=now)

    info = pull_pinned(instance_id)
    info["pruned"] = pruned["removed"]
    return info


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
