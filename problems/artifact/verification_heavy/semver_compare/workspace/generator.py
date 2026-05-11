#!/usr/bin/env python3
"""Workspace generator for verification_heavy__semver_compare. Stdlib-only.

Writes ``examples.json``: seeded sample (a, b, expected) triples covering the
SemVer 2.0.0 precedence rules. The hidden grader runs its own larger set.
"""

from __future__ import annotations
import argparse, json, random
from pathlib import Path


def _version(rng, with_pre=False, with_build=False):
    major = rng.randint(0, 5)
    minor = rng.randint(0, 15)
    patch = rng.randint(0, 30)
    s = f"{major}.{minor}.{patch}"
    if with_pre:
        n = rng.randint(1, 3)
        ids = []
        for _ in range(n):
            if rng.random() < 0.5:
                ids.append(str(rng.randint(0, 30)))
            else:
                ids.append(rng.choice(["alpha", "beta", "rc", "dev", "pre"]))
        s += "-" + ".".join(ids)
    if with_build:
        s += "+build." + str(rng.randint(1, 999))
    return s


def _cmp(a, b):
    # Reference comparator used to label the example. SemVer 2.0.0 logic.
    import re

    def parse(v):
        m = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:-([^+]+))?(?:\+(.+))?$", v)
        if not m:
            raise ValueError(v)
        maj, mnr, pat = int(m.group(1)), int(m.group(2)), int(m.group(3))
        pre = m.group(4)
        return (maj, mnr, pat), pre

    (ma, mb), pa, = parse(a)[:1] + (parse(a)[1],),
    raise RuntimeError  # unreachable; replaced below


def _cmp_real(a, b):
    import re
    pat = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([^+]+))?(?:\+(.+))?$")
    ma = pat.match(a)
    mb = pat.match(b)
    ta = (int(ma.group(1)), int(ma.group(2)), int(ma.group(3)))
    tb = (int(mb.group(1)), int(mb.group(2)), int(mb.group(3)))
    if ta != tb:
        return -1 if ta < tb else 1
    pa = ma.group(4)
    pb = mb.group(4)
    if pa is None and pb is None:
        return 0
    if pa is None:
        return 1
    if pb is None:
        return -1
    ia = pa.split(".")
    ib = pb.split(".")
    for x, y in zip(ia, ib):
        xn = x.isdigit()
        yn = y.isdigit()
        if xn and yn:
            ix, iy = int(x), int(y)
            if ix != iy:
                return -1 if ix < iy else 1
        elif xn and not yn:
            return -1
        elif yn and not xn:
            return 1
        else:
            if x != y:
                return -1 if x < y else 1
    if len(ia) != len(ib):
        return -1 if len(ia) < len(ib) else 1
    return 0


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    examples = []
    for _ in range(10):
        a = _version(rng, with_pre=rng.random() < 0.5, with_build=rng.random() < 0.3)
        b = _version(rng, with_pre=rng.random() < 0.5, with_build=rng.random() < 0.3)
        examples.append({"a": a, "b": b, "expected": _cmp_real(a, b)})
    payload = {
        "description": (
            "Seeded sample SemVer pairs with expected comparison results. The "
            "hidden grader runs its own larger property set."
        ),
        "examples": examples,
    }
    (output_dir / "examples.json").write_text(json.dumps(payload, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--instance-id", type=str, required=False, default="")
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    generate(args.output_dir, args.seed)


if __name__ == "__main__":
    main()
