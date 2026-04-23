"""Hidden grader for algorithmic__knapsack_01.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    The agent's output/pack.json MUST contain a "total_value" key equal to the
    exact optimum of a 0/1 knapsack with the given capacity and (weight, value)
    items.

    If "chosen_ids" is provided, it must be a valid selection (distinct, in
    range, total weight ≤ capacity) and the reported total_value must equal
    the sum of values over those ids.

    Optimum is computed by standard O(N × capacity) DP.

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


INPUT_REL = "parcels.json"
OUTPUT_REL = "output/pack.json"


def _optimal_value(capacity: int, items: list[dict]) -> int:
    n = len(items)
    # dp[w] = best value using any prefix of items with capacity w
    dp = [0] * (capacity + 1)
    for it in items:
        w = it["weight"]
        v = it["value"]
        # iterate right-to-left for 0/1
        for cap in range(capacity, w - 1, -1):
            cand = dp[cap - w] + v
            if cand > dp[cap]:
                dp[cap] = cand
    return dp[capacity]


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()

    inp_path = scratch_dir / INPUT_REL
    if not inp_path.is_file():
        return GradeResult(False, 0.0, f"input {INPUT_REL} not found in scratch dir")

    try:
        inp = json.loads(inp_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse input: {exc}")

    capacity = inp["capacity"]
    items = inp["items"]
    n = len(items)

    output_path = scratch_dir / OUTPUT_REL
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        agent_output = json.loads(output_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse output JSON: {exc}")

    if not isinstance(agent_output, dict):
        return GradeResult(False, 0.0, "output must be a JSON object")

    if "total_value" not in agent_output:
        return GradeResult(False, 0.0, "output missing required key 'total_value'")

    tv = agent_output["total_value"]
    if isinstance(tv, bool) or not isinstance(tv, int):
        return GradeResult(False, 0.0, f"total_value must be integer, got {type(tv).__name__}")

    if "chosen_ids" in agent_output:
        ids = agent_output["chosen_ids"]
        if not isinstance(ids, list):
            return GradeResult(False, 0.0, "chosen_ids must be a list")
        if len(set(ids)) != len(ids):
            return GradeResult(False, 0.0, "chosen_ids contains duplicates")
        for i in ids:
            if not isinstance(i, int) or isinstance(i, bool) or i < 0 or i >= n:
                return GradeResult(False, 0.0, f"chosen_ids contains invalid id {i!r}")
        by_id = {it["id"]: it for it in items}
        total_w = sum(by_id[i]["weight"] for i in ids)
        if total_w > capacity:
            return GradeResult(False, 0.0, f"chosen weight {total_w} exceeds capacity {capacity}")
        total_v = sum(by_id[i]["value"] for i in ids)
        if total_v != tv:
            return GradeResult(
                False, 0.0,
                f"declared total_value {tv} does not match sum over chosen_ids ({total_v})",
            )

    optimal = _optimal_value(capacity, items)
    if tv != optimal:
        return GradeResult(False, 0.0, f"total_value {tv} is not optimal (optimal={optimal})")

    return GradeResult(True, 1.0, f"optimal total_value={optimal}")
