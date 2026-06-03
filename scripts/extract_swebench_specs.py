#!/usr/bin/env python3
"""Regenerate swebench/data/official_specs.json from the upstream SWE-bench package.

The upstream `swebench` PyPI package ships `MAP_REPO_VERSION_TO_SPECS` — the
per-(repo, version) environment recipe (python, packages, pip_packages, install,
test_cmd, …) the official harness builds from. We vendor a filtered copy as JSON
so our harness can build instances to spec without importing that package (its
name collides with ours, so it can't be imported in-process — see swebench/specs.py).

Run this with the **upstream** package installed in an ISOLATED venv (never our
repo venv), then commit the regenerated JSON:

    python3.11 -m venv /tmp/swe-official
    /tmp/swe-official/bin/pip install 'swebench==<pinned>'
    /tmp/swe-official/bin/python scripts/extract_swebench_specs.py \
        --repos-from sets/verified-spine.txt \
        --out swebench/data/official_specs.json

`--repos-from` reads instance ids (e.g. the frozen spine pool) and extracts only
the repos they reference, keeping the vendored file small. Omit it to dump every
repo the upstream map knows.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _repos_from_ids(path: Path) -> set[str]:
    """Derive repo slugs from instance ids like ``django__django-10097``.

    SWE-bench instance ids are ``<owner>__<name>-<number>`` where the repo slug
    is ``<owner>/<name>``. Comment/blank lines are ignored.
    """
    repos: set[str] = set()
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        stem = line.rsplit("-", 1)[0]  # drop the trailing -<number>
        if "__" in stem:
            owner, name = stem.split("__", 1)
            repos.add(f"{owner}/{name}")
    return repos


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=Path("swebench/data/official_specs.json"),
        help="Where to write the vendored JSON (default: swebench/data/official_specs.json).",
    )
    parser.add_argument(
        "--repos-from", type=Path, default=None,
        help="Id file (e.g. sets/verified-spine.txt) — extract only the repos it references.",
    )
    args = parser.parse_args()

    try:
        from swebench.harness.constants import MAP_REPO_VERSION_TO_SPECS
    except ImportError as exc:
        print(
            "ERROR: could not import the upstream swebench package "
            f"({exc}).\nInstall it in an ISOLATED venv (not the repo venv — names "
            "collide):\n  python3.11 -m venv /tmp/swe-official && "
            "/tmp/swe-official/bin/pip install swebench",
            file=sys.stderr,
        )
        return 1

    if args.repos_from:
        wanted = _repos_from_ids(args.repos_from)
        out = {r: MAP_REPO_VERSION_TO_SPECS[r] for r in sorted(wanted)
               if r in MAP_REPO_VERSION_TO_SPECS}
        missing = sorted(wanted - set(out))
        if missing:
            print(f"WARNING: {len(missing)} repo(s) not in upstream map: {missing}",
                  file=sys.stderr)
    else:
        out = dict(MAP_REPO_VERSION_TO_SPECS)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    n_specs = sum(len(v) for v in out.values())
    print(f"Wrote {len(out)} repos / {n_specs} specs to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
