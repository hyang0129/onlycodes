"""Hidden grader for enumeration__graphs_chromatic_3.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    The agent's output/graphs.jsonl MUST list ALL 64 connected graphs on 6
    nodes with chromatic number exactly 3, up to isomorphism (one representative
    per isomorphism class). No duplicates (up to isomorphism), no extra.

    Grader re-enumerates ground truth and uses networkx isomorphism to match.

Determinism: deterministic enumeration, no randomness.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

try:
    import networkx as nx
    _HAS_NX = True
except ImportError:
    _HAS_NX = False


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


OUTPUT_REL = "output/graphs.jsonl"
NUM_NODES = 6


def _can_color(G, n, k):
    color = [-1] * n
    def backtrack(v):
        if v == n:
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


def _chromatic_number(G):
    n = len(G.nodes)
    for k in range(1, n + 1):
        if _can_color(G, n, k):
            return k
    return n


def _enumerate_reference():
    """Return list of all connected 6-node graphs with χ=3, up to isomorphism."""
    import itertools
    nodes = list(range(NUM_NODES))
    all_edges = [(i, j) for i in range(NUM_NODES) for j in range(i + 1, NUM_NODES)]
    result = []
    for mask in range(2 ** len(all_edges)):
        edges = [all_edges[i] for i in range(len(all_edges)) if mask & (1 << i)]
        G = nx.Graph()
        G.add_nodes_from(nodes)
        G.add_edges_from(edges)
        if not nx.is_connected(G):
            continue
        if _chromatic_number(G) != 3:
            continue
        if all(not nx.is_isomorphic(G, h) for h in result):
            result.append(G)
    return result


def _parse_graph(obj) -> "nx.Graph | None":
    """Parse an edge list into a networkx Graph on NUM_NODES nodes, or None on error."""
    if not isinstance(obj, list):
        return None
    G = nx.Graph()
    G.add_nodes_from(range(NUM_NODES))
    for edge in obj:
        if not isinstance(edge, list) or len(edge) != 2:
            return None
        u, v = edge
        if not isinstance(u, int) or not isinstance(v, int):
            return None
        if u == v or u < 0 or v < 0 or u >= NUM_NODES or v >= NUM_NODES:
            return None
        G.add_edge(u, v)
    return G


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()

    if not _HAS_NX:
        return GradeResult(False, 0.0, "grader requires networkx (not installed)")

    output_path = scratch_dir / OUTPUT_REL
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    raw = output_path.read_text()
    if not raw.strip():
        return GradeResult(False, 0.0, "output artifact is empty")

    agent_graphs: list = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            return GradeResult(False, 0.0, f"line {lineno}: JSON parse error: {exc.msg}")
        G = _parse_graph(obj)
        if G is None:
            return GradeResult(
                False, 0.0,
                f"line {lineno}: expected list of [u,v] edges on nodes 0-5, got {obj!r}",
            )
        agent_graphs.append(G)

    if not agent_graphs:
        return GradeResult(False, 0.0, "output contains no graphs")

    # Check for isomorphism-duplicates in agent output
    seen: list = []
    dup_count = 0
    for G in agent_graphs:
        if any(nx.is_isomorphic(G, h) for h in seen):
            dup_count += 1
        else:
            seen.append(G)
    if dup_count:
        return GradeResult(
            False, 0.0,
            f"{dup_count} duplicate graph(s) in output (up to isomorphism) — remove duplicates",
        )
    agent_graphs = seen  # deduped

    # Validate each agent graph: connected? χ=3?
    invalid: list[str] = []
    for i, G in enumerate(agent_graphs):
        if not nx.is_connected(G):
            invalid.append(f"graph {i}: not connected")
        elif _chromatic_number(G) != 3:
            chi = _chromatic_number(G)
            invalid.append(f"graph {i}: chromatic number is {chi}, not 3")
    if invalid:
        return GradeResult(
            False, 0.0,
            f"{len(invalid)} invalid graph(s): " + "; ".join(invalid[:3])
            + (" ..." if len(invalid) > 3 else ""),
        )

    # Enumerate reference
    reference = _enumerate_reference()

    # Count: how many reference graphs are matched by agent?
    matched_ref = 0
    for ref_g in reference:
        if any(nx.is_isomorphic(ref_g, ag) for ag in agent_graphs):
            matched_ref += 1

    n_ref = len(reference)
    n_agent = len(agent_graphs)

    if matched_ref == n_ref and n_agent == n_ref:
        return GradeResult(True, 1.0, f"all {n_ref} graphs enumerated correctly")

    parts = []
    missing = n_ref - matched_ref
    if missing:
        parts.append(f"missing {missing} graph(s)")
    extra = n_agent - matched_ref
    if extra > 0:
        parts.append(f"{extra} graph(s) not in reference set")
    return GradeResult(
        False,
        round(matched_ref / n_ref, 4),
        "; ".join(parts),
    )
