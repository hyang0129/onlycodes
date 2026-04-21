# Task: Enumerate All Connected 6-Node Graphs with Chromatic Number 3

The **chromatic number** χ(G) of a graph G is the minimum number of colors needed to color the vertices such that no two adjacent vertices share the same color.

## Your goal

Enumerate all **non-isomorphic** connected graphs on exactly 6 nodes (vertices 0–5) whose chromatic number is exactly 3.

Two graphs are **isomorphic** if one can be obtained from the other by relabeling the vertices. List exactly one representative per isomorphism class.

## Output

Write `output/graphs.jsonl` — one JSONL line per graph (edge list):

```json
[[0, 1], [0, 2], [1, 2]]
[[0, 1], [1, 2], [2, 3], [3, 0], [0, 2]]
...
```

Each line is a JSON array of edges, where each edge is `[u, v]` with `u < v` and `u, v ∈ {0,1,2,3,4,5}`.
The order of lines and edges within each graph does not matter — all will be normalized by the grader.

## Constraints

- Exactly 6 nodes (labeled 0–5).
- Graph must be **connected**.
- Chromatic number must be **exactly 3** (not 1, 2, or ≥4).
- One representative per isomorphism class (no duplicate non-isomorphic graphs).

## Hints

- χ(G) ≤ 2 iff G is bipartite.
- χ(G) = 3 requires an odd cycle but is not 4-colorable-only (no 4-clique required).
- There are a manageable number of such graphs for n=6.

## Verification

Run `python verify.py` to check that your output has the correct schema.
The hidden grader checks for completeness, no isomorphism-duplicates, and that every listed graph satisfies the constraints.
