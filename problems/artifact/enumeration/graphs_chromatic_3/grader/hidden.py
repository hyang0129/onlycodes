"""Hidden grader for enumeration__graphs_chromatic_3.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    The agent's output/graphs.jsonl MUST list ALL 64 connected graphs on 6
    nodes with chromatic number exactly 3, up to isomorphism (one representative
    per isomorphism class). No duplicates (up to isomorphism), no extra.

How comparison works:

    A *frozen* reference set lives at ``grader/reference_output.jsonl``: 64
    canonical edge lists (lex-smallest sorted edge tuple under any vertex
    permutation). At grade time we load that set, canonicalise each agent
    graph the same way, and check membership. No networkx required.

    The frozen set can be regenerated offline via
    ``tools/regenerate_chromatic_3.py`` (which uses networkx as the trusted
    source for isomorphism).

Determinism: deterministic enumeration, no randomness.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


OUTPUT_REL = "output/graphs.jsonl"
NUM_NODES = 6

REFERENCE_FILE = Path(__file__).parent / "reference_output.jsonl"

_PERMUTATIONS = tuple(itertools.permutations(range(NUM_NODES)))


def _canonical_form(edges):
    """Return the lex-smallest sorted edge tuple over all vertex permutations.

    Two graphs on NUM_NODES vertices are isomorphic iff they share this
    canonical form, so equality on the result is equivalent to networkx's
    ``is_isomorphic`` for our fixed vertex count.
    """
    edge_set = {(min(u, v), max(u, v)) for u, v in edges}
    best = None
    for perm in _PERMUTATIONS:
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
    return best


def _adj(edges, n=NUM_NODES):
    adj = [[] for _ in range(n)]
    for u, v in edges:
        adj[u].append(v)
        adj[v].append(u)
    return adj


def _is_connected(edges, n=NUM_NODES):
    if n <= 1:
        return True
    adj = _adj(edges, n)
    seen = [False] * n
    seen[0] = True
    count = 1
    stack = [0]
    while stack:
        u = stack.pop()
        for w in adj[u]:
            if not seen[w]:
                seen[w] = True
                count += 1
                stack.append(w)
    return count == n


def _can_color(adj, n, k):
    color = [-1] * n

    def backtrack(v):
        if v == n:
            return True
        used = {color[u] for u in adj[v] if color[u] != -1}
        for c in range(k):
            if c not in used:
                color[v] = c
                if backtrack(v + 1):
                    return True
                color[v] = -1
        return False

    return backtrack(0)


def _chromatic_number(edges, n=NUM_NODES):
    adj = _adj(edges, n)
    for k in range(1, n + 1):
        if _can_color(adj, n, k):
            return k
    return n


def _parse_edges(obj):
    """Parse a JSON object as a list of [u,v] edges on NUM_NODES nodes.

    Returns a list of normalised (u,v) tuples with u<v and duplicates removed,
    or None if the input is malformed.
    """
    if not isinstance(obj, list):
        return None
    edges = []
    seen = set()
    for edge in obj:
        if not isinstance(edge, list) or len(edge) != 2:
            return None
        u, v = edge
        if not isinstance(u, int) or not isinstance(v, int):
            return None
        if u == v or u < 0 or v < 0 or u >= NUM_NODES or v >= NUM_NODES:
            return None
        if u > v:
            u, v = v, u
        if (u, v) in seen:
            continue
        seen.add((u, v))
        edges.append((u, v))
    return edges


def _load_reference():
    """Load the frozen reference set as a set of canonical edge tuples."""
    canonical_set = set()
    for lineno, line in enumerate(REFERENCE_FILE.read_text().splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        edges = _parse_edges(obj)
        if edges is None:
            raise RuntimeError(
                f"reference_output.jsonl line {lineno}: malformed edge list {obj!r}"
            )
        canonical_set.add(_canonical_form(edges))
    return canonical_set


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()

    output_path = scratch_dir / OUTPUT_REL
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    raw = output_path.read_text()
    if not raw.strip():
        return GradeResult(False, 0.0, "output artifact is empty")

    agent_graphs = []  # list of (lineno, edges)
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            return GradeResult(False, 0.0, f"line {lineno}: JSON parse error: {exc.msg}")
        edges = _parse_edges(obj)
        if edges is None:
            return GradeResult(
                False, 0.0,
                f"line {lineno}: expected list of [u,v] edges on nodes 0-5, got {obj!r}",
            )
        agent_graphs.append((lineno, edges))

    if not agent_graphs:
        return GradeResult(False, 0.0, "output contains no graphs")

    # Canonicalise once, dedupe by canonical form
    agent_canonical = [(lineno, edges, _canonical_form(edges))
                       for lineno, edges in agent_graphs]

    seen = set()
    dup_count = 0
    deduped = []
    for lineno, edges, canon in agent_canonical:
        if canon in seen:
            dup_count += 1
        else:
            seen.add(canon)
            deduped.append((lineno, edges, canon))
    if dup_count:
        return GradeResult(
            False, 0.0,
            f"{dup_count} duplicate graph(s) in output (up to isomorphism) — remove duplicates",
        )

    # Validate per-graph: must be connected with chromatic number exactly 3.
    # Membership in the frozen reference set already implies these, but we
    # surface the diagnostic separately so agents that submit a chi=4 graph
    # get a precise error instead of just "not in reference set".
    invalid: list[str] = []
    for i, (_lineno, edges, _canon) in enumerate(deduped):
        if not _is_connected(edges):
            invalid.append(f"graph {i}: not connected")
        else:
            chi = _chromatic_number(edges)
            if chi != 3:
                invalid.append(f"graph {i}: chromatic number is {chi}, not 3")
    if invalid:
        return GradeResult(
            False, 0.0,
            f"{len(invalid)} invalid graph(s): " + "; ".join(invalid[:3])
            + (" ..." if len(invalid) > 3 else ""),
        )

    reference = _load_reference()
    matched_ref = sum(1 for _l, _e, canon in deduped if canon in reference)
    n_ref = len(reference)
    n_agent = len(deduped)

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
