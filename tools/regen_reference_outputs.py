#!/usr/bin/env python3
"""Regenerate ``grader/reference_output.json`` for every algorithmic task.

For each task in ``problems/artifact/algorithmic/<slug>/``:

  1. Compute the canonical seed = int(sha256(instance_id)[:8], 16).
  2. Run ``workspace/generator.py`` with that seed against a scratch dir,
     in a scrubbed env that matches SCHEMA §5.1 (only PATH and
     PYTHONDONTWRITEBYTECODE pass through).
  3. Recompute the optimal answer with the corresponding algorithm in this
     script — it mirrors what each task's grader/hidden.py does at grade
     time.
  4. Write the result to ``grader/reference_output.json``.

This script exists for two reasons:

  * The acceptance criteria in #172 require a committed regeneration
    entry point so the reference can be re-derived after any generator
    edit, without having to remember which algorithm each task uses.
  * It documents in one place how each algorithmic task's reference is
    computed from its workspace input — a future task author touching a
    generator can confirm here whether their change will invalidate the
    committed reference (it almost certainly will; regenerate after any
    generator edit).

Usage::

    python tools/regen_reference_outputs.py            # all tasks
    python tools/regen_reference_outputs.py knapsack_01 graph_min_vertex_cover

The script is stdlib-only and runs in a fraction of a second per task.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALGO_ROOT = ROOT / "problems" / "artifact" / "algorithmic"

# Map slug -> (input filename, computer function).
INPUT_FILE = {
    "bin_packing_first_fit_optimal": "parcels.json",
    "coin_change_min": "request.json",
    "graph_min_vertex_cover": "graph.json",
    "interval_scheduling_weighted": "requests.json",
    "knapsack_01": "parcels.json",
    "makespan_scheduling": "jobs.json",
    "min_cost_assignment": "cost_matrix.json",
    "traveling_salesman_small": "stops.json",
}


def canonical_seed(instance_id: str) -> int:
    return int(hashlib.sha256(instance_id.encode()).hexdigest()[:8], 16)


# ── Per-task optimum computations ───────────────────────────────────────────


def compute_knapsack_01(inp: dict) -> dict:
    capacity = inp["capacity"]
    items = inp["items"]
    n = len(items)
    dp = [[0] * (capacity + 1) for _ in range(n + 1)]
    for i, it in enumerate(items, start=1):
        w, v = it["weight"], it["value"]
        for c in range(capacity + 1):
            dp[i][c] = dp[i - 1][c]
            if w <= c and dp[i - 1][c - w] + v > dp[i][c]:
                dp[i][c] = dp[i - 1][c - w] + v
    chosen = []
    c = capacity
    for i in range(n, 0, -1):
        if dp[i][c] != dp[i - 1][c]:
            chosen.append(items[i - 1]["id"])
            c -= items[i - 1]["weight"]
    chosen.sort()
    return {"total_value": dp[n][capacity], "chosen_ids": chosen}


def compute_bin_packing(inp: dict) -> dict:
    capacity = inp["capacity"]
    weights = inp["weights"]
    n = len(weights)
    fits = [False] * (1 << n)
    for m in range(1 << n):
        tot = sum(weights[i] for i in range(n) if m & (1 << i))
        fits[m] = tot <= capacity
    INF = n + 1
    dp = [INF] * (1 << n)
    parent = [0] * (1 << n)
    dp[0] = 0
    for mask in range(1, 1 << n):
        sub = mask
        while sub > 0:
            if fits[sub]:
                rest = mask ^ sub
                if dp[rest] + 1 < dp[mask]:
                    dp[mask] = dp[rest] + 1
                    parent[mask] = sub
            sub = (sub - 1) & mask
    bins: list[list[int]] = []
    m = (1 << n) - 1
    while m:
        sub = parent[m]
        bin_items = [i for i in range(n) if sub & (1 << i)]
        bins.append(bin_items)
        m ^= sub
    bins.sort()
    return {"num_bins": dp[(1 << n) - 1], "bins": bins}


def compute_coin_change(inp: dict) -> dict:
    denoms = inp["denominations"]
    amount = inp["amount"]
    if amount == 0:
        return {"min_coins": 0}
    INF = amount + 1
    dp = [INF] * (amount + 1)
    dp[0] = 0
    for a in range(1, amount + 1):
        for d in denoms:
            if d <= a and dp[a - d] + 1 < dp[a]:
                dp[a] = dp[a - d] + 1
    return {"min_coins": -1 if dp[amount] >= INF else dp[amount]}


def compute_vertex_cover(inp: dict) -> dict:
    n = inp["num_nodes"]
    edges = [tuple(e) for e in inp["edges"]]
    for k in range(0, n + 1):
        for combo in combinations(range(n), k):
            s = set(combo)
            if all((u in s) or (v in s) for (u, v) in edges):
                return {"cover_size": k, "cover": sorted(combo)}
    return {"cover_size": n, "cover": list(range(n))}


def compute_interval_scheduling(inp: dict) -> dict:
    reqs = inp["requests"]
    srt = sorted(reqs, key=lambda r: r["end"])
    n = len(srt)
    p = []
    for i, r in enumerate(srt):
        lo, hi = 0, i - 1
        best = -1
        while lo <= hi:
            mid = (lo + hi) // 2
            if srt[mid]["end"] <= r["start"]:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        p.append(best)
    M = [0] * (n + 1)
    for i in range(1, n + 1):
        r = srt[i - 1]
        take = r["revenue"] + (M[p[i - 1] + 1] if p[i - 1] >= 0 else 0)
        M[i] = max(take, M[i - 1])
    chosen_idx = []
    i = n
    while i > 0:
        r = srt[i - 1]
        take = r["revenue"] + (M[p[i - 1] + 1] if p[i - 1] >= 0 else 0)
        if take >= M[i - 1]:
            chosen_idx.append(i - 1)
            i = p[i - 1] + 1
        else:
            i -= 1
    return {"total_revenue": M[n], "chosen_ids": sorted(srt[k]["id"] for k in chosen_idx)}


def compute_makespan(inp: dict) -> dict:
    m = inp["num_machines"]
    durs = inp["job_durations"]
    n = len(durs)
    best = None
    best_assign = None
    for x in range(m ** n):
        loads = [0] * m
        assign = [[] for _ in range(m)]
        t = x
        for j in range(n):
            k = t % m
            t //= m
            loads[k] += durs[j]
            assign[k].append(j)
        mk = max(loads)
        if best is None or mk < best:
            best = mk
            best_assign = assign
    return {"makespan": best, "assignment": best_assign}


def compute_assignment(inp: dict) -> dict:
    n = inp["num_workers"]
    cost = [row[:] for row in inp["cost_matrix"]]
    INF = float("inf")
    u = [0] * (n + 1)
    v = [0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = INF
            j1 = 0
            for j in range(1, n + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    assignment = [0] * n
    for j in range(1, n + 1):
        if p[j] != 0:
            assignment[p[j] - 1] = j - 1
    total = sum(cost[i][assignment[i]] for i in range(n))
    return {"assignment_cost": total, "assignment": assignment}


def compute_tsp(inp: dict) -> dict:
    pts = inp["points"]
    depot = inp["depot"]
    n = len(pts)
    dist = [[math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1])
             for j in range(n)] for i in range(n)]
    INF = float("inf")
    others = [i for i in range(n) if i != depot]
    m = len(others)
    dp = [[INF] * m for _ in range(1 << m)]
    parent = [[-1] * m for _ in range(1 << m)]
    for k, vtx in enumerate(others):
        dp[1 << k][k] = dist[depot][vtx]
    for mask in range(1, 1 << m):
        for j in range(m):
            if not (mask & (1 << j)) or dp[mask][j] == INF:
                continue
            for k in range(m):
                if mask & (1 << k):
                    continue
                nm = mask | (1 << k)
                cand = dp[mask][j] + dist[others[j]][others[k]]
                if cand < dp[nm][k]:
                    dp[nm][k] = cand
                    parent[nm][k] = j
    full = (1 << m) - 1
    best_cost, best_end = INF, -1
    for j in range(m):
        cand = dp[full][j] + dist[others[j]][depot]
        if cand < best_cost:
            best_cost, best_end = cand, j
    seq = []
    mask, j = full, best_end
    while j != -1:
        seq.append(others[j])
        prev = parent[mask][j]
        mask ^= (1 << j)
        j = prev
    seq.reverse()
    return {"tour_length": best_cost, "tour": [depot] + seq + [depot]}


COMPUTER = {
    "knapsack_01": compute_knapsack_01,
    "bin_packing_first_fit_optimal": compute_bin_packing,
    "coin_change_min": compute_coin_change,
    "graph_min_vertex_cover": compute_vertex_cover,
    "interval_scheduling_weighted": compute_interval_scheduling,
    "makespan_scheduling": compute_makespan,
    "min_cost_assignment": compute_assignment,
    "traveling_salesman_small": compute_tsp,
}


def regen_one(task: str) -> None:
    task_dir = ALGO_ROOT / task
    generator = task_dir / "workspace" / "generator.py"
    out = task_dir / "grader" / "reference_output.json"
    instance_id = f"algorithmic__{task}"
    seed = canonical_seed(instance_id)

    with tempfile.TemporaryDirectory() as td:
        scratch = Path(td)
        env = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}
        rc = subprocess.call(
            [sys.executable, str(generator),
             "--seed", str(seed),
             "--output-dir", str(scratch),
             "--instance-id", instance_id],
            env=env,
        )
        if rc != 0:
            raise SystemExit(f"generator for {task} exited {rc}")
        inp = json.loads((scratch / INPUT_FILE[task]).read_text())
        ref = COMPUTER[task](inp)
        out.write_text(json.dumps(ref, indent=2) + "\n")
        print(f"  regen {task}: {INPUT_FILE[task]} -> reference_output.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks", nargs="*", help="Slugs to regen; default: all.")
    args = ap.parse_args()
    targets = args.tasks or list(COMPUTER.keys())
    unknown = [t for t in targets if t not in COMPUTER]
    if unknown:
        print(f"Unknown task(s): {unknown}", file=sys.stderr)
        print(f"Known: {sorted(COMPUTER)}", file=sys.stderr)
        return 2
    for t in targets:
        regen_one(t)
    return 0


if __name__ == "__main__":
    sys.exit(main())
