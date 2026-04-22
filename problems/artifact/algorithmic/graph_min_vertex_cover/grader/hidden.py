"""Hidden grader for algorithmic__graph_min_vertex_cover.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    The agent's output/cover.json MUST contain "cover_size" equal to the exact
    size of the minimum vertex cover of the given undirected graph.

    If "cover" is provided, it must be a valid vertex cover (every edge has at
    least one endpoint in the set), contain distinct node ids, and its length
    must equal cover_size.

    Optimum is computed by bitmask enumeration: iterate sizes k = 0, 1, 2, ...
    and for each k, iterate all C(n, k) subsets of size k. Return the first k
    for which a subset covers every edge. With n = 18 this is well under a
    second in the worst case.

Determinism: pure function of scratch_dir contents. No clock, no network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


INPUT_REL = "graph.json"
OUTPUT_REL = "output/cover.json"


def _min_cover_size(num_nodes: int, edges: list[tuple[int, int]]) -> int:
    # Encode each edge as a bitmask; a vertex set (as bitmask) covers an edge
    # iff (vertex_mask & edge_mask) != 0.
    edge_masks = [(1 << u) | (1 << v) for u, v in edges]
    # Size-0 cover only works if graph has no edges.
    if not edge_masks:
        return 0
    for k in range(1, num_nodes + 1):
        for combo in combinations(range(num_nodes), k):
            vm = 0
            for v in combo:
                vm |= 1 << v
            ok = True
            for em in edge_masks:
                if vm & em == 0:
                    ok = False
                    break
            if ok:
                return k
    return num_nodes  # trivially, all vertices cover everything


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()

    inp_path = scratch_dir / INPUT_REL
    if not inp_path.is_file():
        return GradeResult(False, 0.0, f"input {INPUT_REL} not found in scratch dir")

    try:
        inp = json.loads(inp_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse input: {exc}")

    n = inp["num_nodes"]
    edges = [tuple(e) for e in inp["edges"]]

    output_path = scratch_dir / OUTPUT_REL
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        agent_output = json.loads(output_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse output JSON: {exc}")

    if not isinstance(agent_output, dict):
        return GradeResult(False, 0.0, "output must be a JSON object")

    if "cover_size" not in agent_output:
        return GradeResult(False, 0.0, "output missing required key 'cover_size'")

    cs = agent_output["cover_size"]
    if isinstance(cs, bool) or not isinstance(cs, int) or cs < 0:
        return GradeResult(False, 0.0, f"cover_size must be a non-negative integer, got {cs!r}")

    if "cover" in agent_output:
        cover = agent_output["cover"]
        if not isinstance(cover, list):
            return GradeResult(False, 0.0, "cover must be a list")
        if len(set(cover)) != len(cover):
            return GradeResult(False, 0.0, "cover contains duplicates")
        for v in cover:
            if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v >= n:
                return GradeResult(False, 0.0, f"cover contains invalid node id {v!r}")
        if len(cover) != cs:
            return GradeResult(False, 0.0, f"cover length {len(cover)} != cover_size {cs}")
        cov = set(cover)
        for u, v in edges:
            if u not in cov and v not in cov:
                return GradeResult(False, 0.0, f"edge ({u},{v}) not covered")

    optimal = _min_cover_size(n, edges)
    if cs != optimal:
        return GradeResult(False, 0.0, f"cover_size {cs} is not optimal (optimal={optimal})")

    return GradeResult(True, 1.0, f"optimal cover_size={optimal}")
