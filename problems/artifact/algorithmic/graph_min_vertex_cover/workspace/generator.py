#!/usr/bin/env python3
"""Workspace generator for algorithmic__graph_min_vertex_cover. Stdlib-only.

Writes ``graph.json``: 18 nodes, ~25-35 edges. Sparse enough that the optimal
cover is well under 18 (so brute-force enumeration is interesting) and dense
enough that greedy-by-degree is not always optimal.
"""

from __future__ import annotations
import argparse, json, random
from pathlib import Path

_N_NODES = 18


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    # Target edge count drives difficulty. Below 18 the graph is forest-like;
    # above 40 the optimal cover approaches N. 25-35 keeps it interesting.
    target_edges = rng.randint(25, 35)
    edges: set[tuple[int, int]] = set()
    safety = 0
    while len(edges) < target_edges and safety < 10_000:
        safety += 1
        u = rng.randint(0, _N_NODES - 1)
        v = rng.randint(0, _N_NODES - 1)
        if u == v:
            continue
        a, b = (u, v) if u < v else (v, u)
        edges.add((a, b))
    edges_list = [[a, b] for (a, b) in sorted(edges)]
    out = {"num_nodes": _N_NODES, "edges": edges_list}
    (output_dir / "graph.json").write_text(json.dumps(out, indent=2))


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
