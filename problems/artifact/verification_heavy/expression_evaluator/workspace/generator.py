#!/usr/bin/env python3
"""Workspace generator for verification_heavy__expression_evaluator. Stdlib-only.

Writes ``examples.json``: seeded arithmetic expressions for development. A few
are syntactically malformed so the agent can validate their ValueError path.
"""

from __future__ import annotations
import argparse, json, random
from pathlib import Path


def _make_expr(rng, depth=0):
    if depth >= 3 or rng.random() < 0.4:
        # Atom: integer or decimal, optionally with unary minus.
        sign = "-" if rng.random() < 0.2 else ""
        if rng.random() < 0.3:
            return f"{sign}{rng.randint(0, 99)}.{rng.randint(0, 99):02d}"
        return f"{sign}{rng.randint(0, 99)}"
    op = rng.choice(["+", "-", "*", "/"])
    a = _make_expr(rng, depth + 1)
    b = _make_expr(rng, depth + 1)
    paren = rng.random() < 0.35
    inner = f"{a} {op} {b}"
    return f"({inner})" if paren else inner


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    examples = [{"expr": _make_expr(rng)} for _ in range(10)]
    # Always include known error cases for shape.
    examples.append({"expr": "1 + "})
    examples.append({"expr": "(2 + 3"})
    payload = {
        "description": (
            "Seeded sample expressions for development. The hidden grader runs "
            "its own larger case set including error paths."
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
