#!/usr/bin/env python3
"""Workspace generator for verification_heavy__cron_next_fire. Stdlib-only.

Writes ``examples.json``: 8 seeded (cron_expr, after) sample inputs the agent
can use as a development sanity check. The actual property tests live in the
hidden grader.
"""

from __future__ import annotations
import argparse, json, random
from pathlib import Path

# Curated cron fragments by field — the generator composes a valid expression
# by drawing one fragment from each pool. All fragments respect the field's
# value range so the produced expression is well-formed.
_MINUTE = ["*", "0", "15", "30", "45", "0,30", "*/5", "*/10", "0-29"]
_HOUR = ["*", "0", "9", "12", "9-17", "0,12", "*/6", "*/3"]
_DOM = ["*", "1", "15", "1,15", "1-5"]
_MONTH = ["*", "1", "6", "1,7", "*/3"]
_DOW = ["*", "0", "1", "5", "1-5", "0,6"]


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    examples = []
    for _ in range(8):
        expr_parts = [
            rng.choice(_MINUTE),
            rng.choice(_HOUR),
            rng.choice(_DOM),
            rng.choice(_MONTH),
            rng.choice(_DOW),
        ]
        year = rng.randint(2023, 2026)
        month = rng.randint(1, 12)
        day = rng.randint(1, 28)
        hour = rng.randint(0, 23)
        minute = rng.randint(0, 59)
        examples.append({
            "expr": " ".join(expr_parts),
            "after": f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:00",
        })
    payload = {
        "description": (
            "Seeded sample inputs for development. The hidden grader runs its "
            "own larger test set; passing these examples is necessary but not "
            "sufficient."
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
