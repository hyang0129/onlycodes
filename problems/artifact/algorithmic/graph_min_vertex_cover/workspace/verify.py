#!/usr/bin/env python3
"""Structural verifier for algorithmic__graph_min_vertex_cover."""

import json
import sys
from pathlib import Path

GRAPH = Path(__file__).parent / "graph.json"
OUTPUT = Path(__file__).parent / "output" / "cover.json"


def main() -> int:
    if not GRAPH.is_file():
        print(f"FAIL: graph.json not found at {GRAPH}", file=sys.stderr)
        return 1
    data = json.loads(GRAPH.read_text())
    n = data["num_nodes"]
    edges = data["edges"]

    if not OUTPUT.is_file():
        print(f"FAIL: output file not found: {OUTPUT}", file=sys.stderr)
        return 1
    try:
        out = json.loads(OUTPUT.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: could not parse output JSON: {exc}", file=sys.stderr)
        return 1

    if not isinstance(out, dict):
        print("FAIL: output must be a JSON object", file=sys.stderr)
        return 1

    if "cover_size" not in out:
        print("FAIL: missing required key 'cover_size'", file=sys.stderr)
        return 1

    cs = out["cover_size"]
    if isinstance(cs, bool) or not isinstance(cs, int) or cs < 0:
        print(f"FAIL: cover_size must be a non-negative integer, got {cs}", file=sys.stderr)
        return 1

    if "cover" in out:
        cover = out["cover"]
        if not isinstance(cover, list) or any(
            not isinstance(v, int) or isinstance(v, bool) or v < 0 or v >= n
            for v in cover
        ):
            print("FAIL: cover must be a list of valid node ids", file=sys.stderr)
            return 1
        if len(set(cover)) != len(cover):
            print("FAIL: cover contains duplicates", file=sys.stderr)
            return 1
        if len(cover) != cs:
            print(f"FAIL: cover length {len(cover)} does not match cover_size {cs}", file=sys.stderr)
            return 1
        cov = set(cover)
        for u, v in edges:
            if u not in cov and v not in cov:
                print(f"FAIL: edge ({u},{v}) not covered", file=sys.stderr)
                return 1

    print(f"OK: cover_size={cs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
