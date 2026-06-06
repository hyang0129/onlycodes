"""Backfill ``swebench/data/verified_image_digests.json`` (C3b #323).

Resolve each Verified instance's official image to a content digest **without
pulling** (registry manifest inspect via ``buildx imagetools``), so runs pin to
an exact image rather than the moving ``:latest`` tag.

Authenticate first (``ONLYCODES_DOCKERHUB_TOKEN``) — resolving ~500 manifests
anonymously will hit Docker Hub's rate limit. Idempotent: skips instances
already in the manifest unless ``--force``.

    # all 500 from a frozen id list
    python scripts/resolve_image_digests.py --from-file verified-spine.txt
    # a few explicit ids
    python scripts/resolve_image_digests.py --ids psf__requests-1142,django__django-10097
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from swebench import container, image_store as ims  # noqa: E402


def _read_ids(args: argparse.Namespace) -> list[str]:
    ids: list[str] = []
    if args.ids:
        ids += [s.strip() for s in args.ids.split(",") if s.strip()]
    if args.from_file:
        for line in Path(args.from_file).read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                ids.append(line)
    # de-dup, preserve order
    seen: set[str] = set()
    return [i for i in ids if not (i in seen or seen.add(i))]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-file", help="file of instance ids (one per line, # comments ok)")
    ap.add_argument("--ids", help="comma-separated instance ids")
    ap.add_argument("--force", action="store_true", help="re-resolve ids already in the manifest")
    args = ap.parse_args()

    ids = _read_ids(args)
    if not ids:
        ap.error("provide --from-file and/or --ids")

    if not ims.registry_login():
        print("WARNING: no ONLYCODES_DOCKERHUB_TOKEN — resolving anonymously "
              "(rate-limited; fine for a handful, not 500).", file=sys.stderr)

    manifest = ims.load_digest_manifest()
    resolved = skipped = failed = 0
    for iid in ids:
        if iid in manifest and not args.force:
            skipped += 1
            continue
        try:
            digest = ims.resolve_remote_digest(container.official_image_for(iid))
            ims.record_digest(iid, digest)
            resolved += 1
            print(f"{iid} {digest}")
        except Exception as e:  # noqa: BLE001 — report and continue the sweep
            failed += 1
            print(f"WARN {iid}: {e}", file=sys.stderr)

    print(f"\nresolved={resolved} skipped={skipped} failed={failed} "
          f"(manifest now {len(ims.load_digest_manifest())} entries)", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
