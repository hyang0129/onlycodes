#!/usr/bin/env python3
"""Workspace generator for verification_heavy__parse_iso_duration. Stdlib-only.

Writes ``examples.json``: seeded ISO 8601 duration strings the agent can use
for development. The hidden grader runs its own larger property set.
"""

from __future__ import annotations
import argparse, json, random
from pathlib import Path


def _maybe(rng, prob=0.5):
    return rng.random() < prob


def _component_int(rng, lo, hi):
    return str(rng.randint(lo, hi))


def _component_decimal(rng, lo, hi):
    whole = rng.randint(lo, hi)
    frac = rng.randint(0, 9)
    return f"{whole}.{frac}"


def _make_duration(rng):
    parts_date = []
    parts_time = []
    if _maybe(rng, 0.5):
        parts_date.append(_component_int(rng, 1, 6) + "W")
    if _maybe(rng, 0.6):
        parts_date.append(_component_int(rng, 1, 30) + "D")
    if _maybe(rng, 0.6):
        h = _component_decimal(rng, 0, 12) if _maybe(rng, 0.2) else _component_int(rng, 1, 23)
        parts_time.append(h + "H")
    if _maybe(rng, 0.6):
        parts_time.append(_component_int(rng, 1, 59) + "M")
    if _maybe(rng, 0.5):
        s = _component_decimal(rng, 0, 59) if _maybe(rng, 0.25) else _component_int(rng, 1, 59)
        parts_time.append(s + "S")
    if not parts_date and not parts_time:
        return "PT0S"
    s = "P" + "".join(parts_date)
    if parts_time:
        s += "T" + "".join(parts_time)
    return s


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    examples = [{"duration": _make_duration(rng)} for _ in range(10)]
    payload = {
        "description": (
            "Seeded sample ISO 8601 duration strings for development. The "
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
