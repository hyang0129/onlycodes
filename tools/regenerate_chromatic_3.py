#!/usr/bin/env python3
"""Regenerate the frozen reference set for enumeration__graphs_chromatic_3.

This is an offline tool: it uses networkx as the trusted source for graph
isomorphism, enumerates every isomorphism class of connected 6-node graphs
with chromatic number 3, canonicalises each class to the lex-smallest edge
list under any vertex permutation, and writes the result to
``problems/artifact/enumeration/graphs_chromatic_3/grader/reference_output.jsonl``.

The grader (``grader/hidden.py``) consumes that file at grade time and does
NOT require networkx itself — see the docstring there for the comparison
strategy.

Usage (from any directory inside the repo)::

    pip install networkx
    python tools/regenerate_chromatic_3.py

The script is idempotent: running it twice on the same Python version
produces byte-identical output (canonical forms are sorted lexicographically
before writing).
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import networkx as nx

N = 6
ALL_EDGES: list[tuple[int, int]] = [
    (i, j) for i in range(N) for j in range(i + 1, N)
]
NUM_EDGES = len(ALL_EDGES)  # 15

REPO_ROOT = Path(__file__).resolve().parents[1]
REF_FILE = (
    REPO_ROOT
    / "problems"
    / "artifact"
    / "enumeration"
    / "graphs_chromatic_3"
    / "grader"
    / "reference_output.jsonl"
)


def _can_color(G: nx.Graph, k: int) -> bool:
    color = [-1] * N

    def backtrack(v: int) -> bool:
        if v == N:
            return True
        used = {color[u] for u in G.neighbors(v) if color[u] != -1}
        for c in range(k):
            if c not in used:
                color[v] = c
                if backtrack(v + 1):
                    return True
                color[v] = -1
        return False

    return backtrack(0)


def chromatic_number(G: nx.Graph) -> int:
    for k in range(1, N + 1):
        if _can_color(G, k):
            return k
    return N


def canonical_form(edges: list[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    """Return the lex-smallest sorted edge tuple under any vertex permutation."""
    edge_set = {(min(u, v), max(u, v)) for u, v in edges}
    best: tuple[tuple[int, int], ...] | None = None
    for perm in itertools.permutations(range(N)):
        relabelled = []
        for u, v in edge_set:
            pu, pv = perm[u], perm[v]
            if pu > pv:
                pu, pv = pv, pu
            relabelled.append((pu, pv))
        relabelled.sort()
        candidate = tuple(relabelled)
        if best is None or candidate < best:
            best = candidate
    assert best is not None
    return best


def main() -> int:
    canonical_set: set[tuple[tuple[int, int], ...]] = set()
    classes: list[nx.Graph] = []
    for mask in range(2 ** NUM_EDGES):
        edges = [ALL_EDGES[i] for i in range(NUM_EDGES) if mask & (1 << i)]
        G = nx.Graph()
        G.add_nodes_from(range(N))
        G.add_edges_from(edges)
        if not nx.is_connected(G):
            continue
        if chromatic_number(G) != 3:
            continue
        if any(nx.is_isomorphic(G, h) for h in classes):
            continue
        classes.append(G)
        canonical_set.add(canonical_form(edges))

    if len(classes) != len(canonical_set):
        raise SystemExit(
            f"FATAL: networkx isomorphism classes ({len(classes)}) and "
            f"canonical forms ({len(canonical_set)}) disagree"
        )
    print(f"Enumerated {len(classes)} non-isomorphic connected 6-node "
          f"graphs with chi=3 (networkx)")

    lines = [json.dumps([[u, v] for u, v in canon]) for canon in canonical_set]
    lines.sort()
    REF_FILE.parent.mkdir(parents=True, exist_ok=True)
    REF_FILE.write_text("\n".join(lines) + "\n")
    print(f"Wrote {len(lines)} canonical edge lists to {REF_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
