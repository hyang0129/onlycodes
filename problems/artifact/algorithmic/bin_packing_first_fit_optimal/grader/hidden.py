"""Hidden grader for algorithmic__bin_packing_first_fit_optimal.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    The agent's output/bins.json MUST contain "num_bins" equal to the exact
    minimum number of bins needed to pack all items (classic 1D bin packing,
    every item must be placed, no split).

    If "bins" is provided, it must be a valid partition of the items into
    num_bins bins, each with total weight <= capacity.

    Optimum is computed via subset DP:
        dp[mask] = min bins needed to cover items in `mask`,
    iterating each mask's submasks that fit in a single bin.
    For N=15 this is ~32k * submask-enumeration → well under a second.

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
OUTPUT_REL = "output/bins.json"


def _min_bins(weights: list[int], capacity: int) -> int:
    n = len(weights)
    full = (1 << n) - 1

    # Precompute which masks fit in a single bin.
    # weight_of_mask[m] = sum of weights of bits set in m.
    wom = [0] * (1 << n)
    for m in range(1, 1 << n):
        low = m & -m
        wom[m] = wom[m ^ low] + weights[low.bit_length() - 1]

    fits = [False] * (1 << n)
    for m in range(1 << n):
        fits[m] = wom[m] <= capacity

    # dp[mask] = min bins to cover items in mask
    INF = n + 1
    dp = [INF] * (1 << n)
    dp[0] = 0
    for mask in range(1, 1 << n):
        # Enumerate non-empty submasks that fit in one bin.
        sub = mask
        best = INF
        while sub > 0:
            if fits[sub]:
                cand = dp[mask ^ sub] + 1
                if cand < best:
                    best = cand
            sub = (sub - 1) & mask
        dp[mask] = best
    return dp[full]


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()

    inp_path = scratch_dir / INPUT_REL
    if not inp_path.is_file():
        return GradeResult(False, 0.0, f"input {INPUT_REL} not found in scratch dir")

    try:
        inp = json.loads(inp_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse input: {exc}")

    weights = inp["weights"]
    capacity = inp["capacity"]
    n = len(weights)

    output_path = scratch_dir / OUTPUT_REL
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        agent_output = json.loads(output_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse output JSON: {exc}")

    if not isinstance(agent_output, dict):
        return GradeResult(False, 0.0, "output must be a JSON object")

    if "num_bins" not in agent_output:
        return GradeResult(False, 0.0, "output missing required key 'num_bins'")

    nb = agent_output["num_bins"]
    if isinstance(nb, bool) or not isinstance(nb, int) or nb <= 0:
        return GradeResult(False, 0.0, f"num_bins must be a positive integer, got {nb!r}")

    if "bins" in agent_output:
        bins = agent_output["bins"]
        if not isinstance(bins, list) or len(bins) != nb:
            return GradeResult(False, 0.0, f"bins must be a list of length {nb}")
        seen: set[int] = set()
        for idx, grp in enumerate(bins):
            if not isinstance(grp, list) or not grp:
                return GradeResult(False, 0.0, f"bin {idx} must be a non-empty list")
            tot = 0
            for j in grp:
                if not isinstance(j, int) or isinstance(j, bool) or j < 0 or j >= n:
                    return GradeResult(False, 0.0, f"bin {idx} has invalid id {j!r}")
                if j in seen:
                    return GradeResult(False, 0.0, f"item {j} appears in more than one bin")
                seen.add(j)
                tot += weights[j]
            if tot > capacity:
                return GradeResult(False, 0.0, f"bin {idx} weight {tot} > capacity {capacity}")
        if seen != set(range(n)):
            return GradeResult(False, 0.0, "bins do not cover every item exactly once")

    optimal = _min_bins(weights, capacity)
    if nb != optimal:
        return GradeResult(False, 0.0, f"num_bins {nb} is not optimal (optimal={optimal})")

    return GradeResult(True, 1.0, f"optimal num_bins={optimal}")
