#!/usr/bin/env python3
"""Structural verifier for enumeration__graphs_chromatic_3.

Checks output/graphs.jsonl:
  - valid JSONL
  - each line is a list of [u, v] integer pairs (edges)
  - all node ids in [0, 5]

Does NOT check connectivity, chromatic number, or completeness.
"""

import json
import sys
from pathlib import Path

OUTPUT = Path(__file__).parent / "output" / "graphs.jsonl"
NUM_NODES = 6


def main() -> int:
    if not OUTPUT.is_file():
        print(f"FAIL: {OUTPUT} not found", file=sys.stderr)
        return 1

    graphs_seen = 0
    for lineno, line in enumerate(OUTPUT.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"FAIL: line {lineno}: JSON error: {exc.msg}", file=sys.stderr)
            return 1
        if not isinstance(obj, list):
            print(f"FAIL: line {lineno}: expected a list of edges", file=sys.stderr)
            return 1
        for ei, edge in enumerate(obj):
            if not isinstance(edge, list) or len(edge) != 2:
                print(f"FAIL: line {lineno} edge {ei}: expected [u, v]", file=sys.stderr)
                return 1
            u, v = edge
            if not isinstance(u, int) or not isinstance(v, int):
                print(f"FAIL: line {lineno} edge {ei}: u and v must be integers", file=sys.stderr)
                return 1
            if u < 0 or u >= NUM_NODES or v < 0 or v >= NUM_NODES:
                print(
                    f"FAIL: line {lineno} edge {ei}: node ids must be in [0, {NUM_NODES-1}]",
                    file=sys.stderr,
                )
                return 1
        graphs_seen += 1

    if graphs_seen == 0:
        print("FAIL: no graphs found in output", file=sys.stderr)
        return 1

    print(f"OK: {graphs_seen} candidate graph(s) with correct schema")
    return 0


if __name__ == "__main__":
    sys.exit(main())
