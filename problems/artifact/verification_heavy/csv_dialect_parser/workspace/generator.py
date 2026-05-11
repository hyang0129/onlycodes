#!/usr/bin/env python3
"""Workspace generator for verification_heavy__csv_dialect_parser. Stdlib-only.

Writes ``examples.json``: seeded sample CSV records that cover the rules the
agent's parse_csv_line must implement.
"""

from __future__ import annotations
import argparse, json, random
from pathlib import Path

_WORD_POOL = ["foo", "bar", "baz", "qux", "Seattle", "WA", "98101", "1", "2",
              "alpha", "beta", "gamma", "Seattle, WA", "say \"hi\"", "Smith",
              "Jane", "x y z", "", " "]


def _field(rng):
    w = rng.choice(_WORD_POOL)
    needs_quotes = ("," in w) or ('"' in w) or rng.random() < 0.2
    if needs_quotes:
        inner = w.replace('"', '""')
        return f'"{inner}"'
    return w


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    examples = []
    for _ in range(10):
        n_fields = rng.randint(1, 5)
        line = ",".join(_field(rng) for _ in range(n_fields))
        examples.append({"line": line})
    # Always include the canonical empty-string edge case.
    examples.append({"line": ""})
    payload = {
        "description": (
            "Seeded sample CSV records for development. The hidden grader runs "
            "its own larger fixed-case suite."
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
