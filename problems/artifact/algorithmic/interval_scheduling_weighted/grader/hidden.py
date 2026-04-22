"""Hidden grader for algorithmic__interval_scheduling_weighted.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    The agent's output/schedule.json MUST contain "total_revenue" equal to the
    exact optimum of weighted interval scheduling.

    If "chosen_ids" is provided, it must be a valid non-overlapping subset
    whose revenue sum equals total_revenue.

    Optimum is computed via the classical sort-by-end + DP + binary-search
    predecessor lookup (O(n log n)).

Determinism: pure function of scratch_dir contents. No clock, no network.
"""

from __future__ import annotations

import bisect
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


INPUT_REL = "requests.json"
OUTPUT_REL = "output/schedule.json"


def _optimal_revenue(requests: list[dict]) -> int:
    items = sorted(requests, key=lambda r: r["end"])
    n = len(items)
    ends = [r["end"] for r in items]
    dp = [0] * (n + 1)
    for i in range(1, n + 1):
        r = items[i - 1]
        # Predecessor: largest j with items[j-1].end <= r.start
        j = bisect.bisect_right(ends, r["start"], hi=i - 1)
        take = r["revenue"] + dp[j]
        dp[i] = max(dp[i - 1], take)
    return dp[n]


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()

    inp_path = scratch_dir / INPUT_REL
    if not inp_path.is_file():
        return GradeResult(False, 0.0, f"input {INPUT_REL} not found in scratch dir")

    try:
        inp = json.loads(inp_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse input: {exc}")

    requests = inp["requests"]
    by_id = {r["id"]: r for r in requests}

    output_path = scratch_dir / OUTPUT_REL
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        agent_output = json.loads(output_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse output JSON: {exc}")

    if not isinstance(agent_output, dict):
        return GradeResult(False, 0.0, "output must be a JSON object")

    if "total_revenue" not in agent_output:
        return GradeResult(False, 0.0, "output missing required key 'total_revenue'")

    tr = agent_output["total_revenue"]
    if isinstance(tr, bool) or not isinstance(tr, int):
        return GradeResult(False, 0.0, "total_revenue must be an integer")

    if "chosen_ids" in agent_output:
        ids = agent_output["chosen_ids"]
        if not isinstance(ids, list):
            return GradeResult(False, 0.0, "chosen_ids must be a list")
        if len(set(ids)) != len(ids):
            return GradeResult(False, 0.0, "chosen_ids contains duplicates")
        for i in ids:
            if not isinstance(i, int) or isinstance(i, bool) or i not in by_id:
                return GradeResult(False, 0.0, f"chosen_ids contains invalid id {i!r}")
        chosen = sorted((by_id[i] for i in ids), key=lambda r: r["start"])
        for a, b in zip(chosen[:-1], chosen[1:]):
            if a["end"] > b["start"]:
                return GradeResult(False, 0.0, f"overlap between {a['id']} and {b['id']}")
        rev_sum = sum(r["revenue"] for r in chosen)
        if rev_sum != tr:
            return GradeResult(
                False, 0.0,
                f"declared total_revenue {tr} does not match sum over chosen_ids ({rev_sum})",
            )

    optimal = _optimal_revenue(requests)
    if tr != optimal:
        return GradeResult(False, 0.0, f"total_revenue {tr} is not optimal (optimal={optimal})")

    return GradeResult(True, 1.0, f"optimal total_revenue={optimal}")
