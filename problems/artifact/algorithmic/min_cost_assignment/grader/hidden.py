"""Hidden grader for algorithmic__min_cost_assignment.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    The agent's output/assignment.json MUST contain an "assignment" key
    (list of num_workers ints, assignment[worker] = task) representing a
    perfect matching whose total cost equals the optimal minimum cost.
    The grader accepts any optimal-cost assignment — identity is not checked.

    Optimal cost is computed via the Hungarian algorithm (pure Python,
    no scipy dependency — see _hungarian below).

Determinism: pure function of scratch_dir contents. No clock, no network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


INPUT_REL = "cost_matrix.json"
OUTPUT_REL = "output/assignment.json"


# ─── O(n^3) Hungarian algorithm (pure Python) ─────────────────────────────

def _hungarian(cost: list[list[int]]) -> int:
    """Return the minimum cost of a perfect matching on an n×n cost matrix."""
    n = len(cost)
    INF = float('inf')

    # Potential vectors
    u = [0] * (n + 1)
    v = [0] * (n + 1)
    p = [0] * (n + 1)   # p[j] = row matched to column j (1-indexed), 0=unmatched
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
            j1 = -1
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
            p[j0] = p[way[j0]]
            j0 = way[j0]

    # Extract matching and compute cost
    ans = [0] * (n + 1)  # ans[i] = column assigned to row i (1-indexed)
    for j in range(1, n + 1):
        if p[j] != 0:
            ans[p[j]] = j

    total = sum(cost[i - 1][ans[i] - 1] for i in range(1, n + 1))
    return total


def _load_cost_matrix(scratch_dir: Path):
    p = scratch_dir / INPUT_REL
    if not p.is_file():
        return None
    data = json.loads(p.read_text())
    return data["cost_matrix"], data["num_workers"]


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()

    inp = _load_cost_matrix(scratch_dir)
    if inp is None:
        return GradeResult(False, 0.0, f"input {INPUT_REL} not found in scratch dir")
    cost_matrix, num_workers = inp

    output_path = scratch_dir / OUTPUT_REL
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        agent_output = json.loads(output_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse output JSON: {exc}")

    if not isinstance(agent_output, dict):
        return GradeResult(False, 0.0, "output must be a JSON object")

    if "assignment" not in agent_output:
        return GradeResult(False, 0.0, "output missing required key 'assignment'")

    assignment = agent_output["assignment"]
    if not isinstance(assignment, list) or len(assignment) != num_workers:
        return GradeResult(
            False, 0.0,
            f"assignment must be a list of {num_workers} integers, "
            f"got {type(assignment).__name__} of length {len(assignment) if isinstance(assignment, list) else '?'}",
        )

    # Validate: perfect matching — each task assigned exactly once
    assigned_tasks = set()
    for i, task in enumerate(assignment):
        if not isinstance(task, int) or isinstance(task, bool):
            return GradeResult(False, 0.0, f"assignment[{i}] must be an integer")
        if task < 0 or task >= num_workers:
            return GradeResult(
                False, 0.0,
                f"assignment[{i}]={task} is out of range [0, {num_workers-1}]",
            )
        if task in assigned_tasks:
            return GradeResult(
                False, 0.0,
                f"assignment[{i}]={task} is a duplicate (task assigned to multiple workers)",
            )
        assigned_tasks.add(task)

    # Compute agent's total cost
    agent_cost = sum(cost_matrix[i][assignment[i]] for i in range(num_workers))

    # Compute optimal
    optimal_cost = _hungarian(cost_matrix)

    if agent_cost != optimal_cost:
        return GradeResult(
            False, 0.0,
            f"assignment cost {agent_cost} is not optimal (optimal={optimal_cost})",
        )

    return GradeResult(True, 1.0, f"optimal assignment cost {optimal_cost} achieved")
