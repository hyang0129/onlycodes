# Task: Monitoring Placement — Minimum Vertex Cover

Our network monitoring team models the office LAN as an undirected graph: nodes
are switches, edges are physical links. Every link must be observed by a
monitor attached to at least one of its two endpoint switches. Monitors are
expensive — we want to deploy as few as possible while still covering every
link.

**Find the minimum number of switches that must host a monitor so that every
link has at least one monitored endpoint.** Report the size of the minimum
vertex cover and, optionally, one witness set of that size.

## Input

Read `graph.json` from your working directory:

```json
{
  "num_nodes": 18,
  "edges": [[0, 4], [1, 7], [2, 9], ...]
}
```

- `num_nodes`: number of switches, exactly 18. Nodes are 0-indexed.
- `edges`: list of `[u, v]` pairs (`u != v`). The graph is undirected; each
  pair appears at most once (in either order).

## Output

Write `output/cover.json`:

```json
{
  "cover_size": <integer>,
  "cover": [<list of node ids forming a minimum vertex cover>]
}
```

- `cover_size`: the minimum vertex-cover size. Must equal the global optimum.
- `cover`: (optional but validated if present) a list of distinct node ids whose
  length equals `cover_size` and such that every edge has at least one endpoint
  in the list.

## Requirements

- `cover_size` must be **globally optimal**. Minimum vertex cover is NP-hard in
  general, but with N=18 nodes there are only `2^18 ≈ 262 144` subsets to
  consider. A brute-force enumeration over subsets of the 18 nodes (ordered by
  popcount, returning the first cover found) is fast in pure Python. Greedy
  (pick the highest-degree vertex, remove its edges, repeat) is NOT guaranteed
  to be optimal.

## Verification

Run `python verify.py` to check your output has the correct shape before submitting.
