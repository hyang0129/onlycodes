"""Hidden grader for algorithmic__coin_change_min.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    The agent's output/answer.json MUST contain a "min_coins" key whose value
    equals the exact minimum number of coins needed to make `amount` using
    unbounded quantities of the given denominations, or -1 if unreachable.

    Optimum is computed by standard unbounded-coin-change DP in O(amount * k).

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


INPUT_REL = "request.json"
OUTPUT_REL = "output/answer.json"


def _optimal_min_coins(denominations: list[int], amount: int) -> int:
    if amount == 0:
        return 0
    INF = amount + 1
    dp = [INF] * (amount + 1)
    dp[0] = 0
    for a in range(1, amount + 1):
        for d in denominations:
            if d <= a and dp[a - d] + 1 < dp[a]:
                dp[a] = dp[a - d] + 1
    return -1 if dp[amount] == INF else dp[amount]


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()

    inp_path = scratch_dir / INPUT_REL
    if not inp_path.is_file():
        return GradeResult(False, 0.0, f"input {INPUT_REL} not found in scratch dir")

    try:
        inp = json.loads(inp_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse input: {exc}")

    denominations = inp["denominations"]
    amount = inp["amount"]

    output_path = scratch_dir / OUTPUT_REL
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        agent_output = json.loads(output_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse output JSON: {exc}")

    if not isinstance(agent_output, dict):
        return GradeResult(False, 0.0, "output must be a JSON object")

    if "min_coins" not in agent_output:
        return GradeResult(False, 0.0, "output missing required key 'min_coins'")

    agent_mc = agent_output["min_coins"]
    if isinstance(agent_mc, bool) or not isinstance(agent_mc, int):
        return GradeResult(
            False, 0.0,
            f"min_coins must be an integer, got {type(agent_mc).__name__}",
        )

    optimal = _optimal_min_coins(denominations, amount)

    if agent_mc != optimal:
        return GradeResult(
            False, 0.0,
            f"min_coins {agent_mc} is not optimal (optimal={optimal})",
        )

    return GradeResult(True, 1.0, f"optimal min_coins={optimal}")
