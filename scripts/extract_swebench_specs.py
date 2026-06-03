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
    /tmp/swe-official/bin/pip install 'swebench==4.1.0'
    /tmp/swe-official/bin/python scripts/extract_swebench_specs.py \
        --repos-from sets/verified-spine.txt \
        --out swebench/data/official_specs.json

The pin matters: a different upstream `swebench` may ship a different
`MAP_REPO_VERSION_TO_SPECS`, silently changing the vendored specs (and thus how
every Verified instance builds). **`swebench==4.1.0` reproduces the committed
`swebench/data/official_specs.json` byte-for-byte (verified 2026-06-03, #311).**
After regenerating, `git diff swebench/data/official_specs.json` should be empty
unless you intentionally bumped the pin.

`--repos-from` reads instance ids (e.g. the frozen spine pool) and extracts only
the repos they reference, keeping the vendored file small. Omit it to dump every
repo the upstream map knows.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Upstream package version this extractor is pinned to (see module docstring).
PINNED_SWEBENCH_VERSION = "4.1.0"


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
            f"/tmp/swe-official/bin/pip install 'swebench=={PINNED_SWEBENCH_VERSION}'",
            file=sys.stderr,
        )
        return 1

    # Warn loudly if the installed version isn't the pin — the map can drift
    # between releases and silently change the vendored specs (#311).
    try:
        import importlib.metadata as _md
        installed = _md.version("swebench")
        if installed != PINNED_SWEBENCH_VERSION:
            print(
                f"WARNING: swebench=={installed} installed, but this extractor is "
                f"pinned to {PINNED_SWEBENCH_VERSION}. The vendored JSON was generated "
                f"from {PINNED_SWEBENCH_VERSION}; regenerating from a different version "
                "may change specs. Re-pin (and re-validate) deliberately.",
                file=sys.stderr,
            )
    except Exception:  # noqa: BLE001 — metadata lookup is best-effort
        pass

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
