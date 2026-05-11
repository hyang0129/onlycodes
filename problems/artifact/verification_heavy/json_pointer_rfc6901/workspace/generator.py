#!/usr/bin/env python3
"""Workspace generator for verification_heavy__json_pointer_rfc6901. Stdlib-only.

Writes ``examples.json``: a seeded JSON document plus a list of sample resolve()
pointers and set_at() (pointer, value) pairs. The agent can replay these
against their implementation for development.
"""

from __future__ import annotations
import argparse, json, random
from pathlib import Path


def _build_doc(rng: random.Random):
    return {
        "service": "checkout",
        "endpoints": {
            "create": {"path": "/v1/orders", "method": "POST",
                       "timeouts": {"read_s": rng.randint(1, 20),
                                    "write_s": rng.randint(1, 20)}},
            "get": {"path": "/v1/orders/{id}", "method": "GET"},
        },
        "tags": ["payments", "high-priority"],
        "flags": {"experimental": rng.random() < 0.5},
        "matrix": [[rng.randint(0, 9) for _ in range(3)] for _ in range(3)],
        "": "empty-key",
        "weird~key/with/slashes": rng.randint(100, 999),
    }


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    doc = _build_doc(rng)
    resolves = [
        "",
        "/service",
        "/endpoints/create/method",
        f"/endpoints/create/timeouts/read_s",
        "/tags/0",
        "/matrix/1/2",
        "/",
        "/weird~0key~1with~1slashes",
    ]
    sets = [
        {"pointer": "/flags/experimental", "value": True},
        {"pointer": "/endpoints/create/timeouts/read_s", "value": rng.randint(50, 99)},
        {"pointer": "/tags/-", "value": "new-tag"},  # append
    ]
    payload = {
        "description": (
            "Seeded sample document, resolve() pointers, and set_at() ops for "
            "development. The hidden grader runs its own larger property set."
        ),
        "doc": doc,
        "resolves": resolves,
        "sets": sets,
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
