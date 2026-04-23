"""Hidden grader for algorithmic__traveling_salesman_small.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    The agent's output/tour.json MUST contain:
      - "tour": list of N+1 ints, starts & ends at depot, Hamiltonian on the
        non-depot indices.
      - "tour_length": float equal (within 1e-6 relative tolerance) to the
        optimal tour length AND to the computed length of the declared tour.

    Optimum is computed by Held–Karp bitmask DP over 2^N * N^2 states (pure
    Python, no external deps).

Determinism: pure function of scratch_dir contents. No clock, no network.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


INPUT_REL = "stops.json"
OUTPUT_REL = "output/tour.json"

_TOL = 1e-6


def _dist(pts, i, j):
    ax, ay = pts[i]
    bx, by = pts[j]
    return math.hypot(ax - bx, ay - by)


def _optimal_tour_length(points: list[list[float]], depot: int) -> float:
    """Held–Karp: minimum-cost Hamiltonian cycle starting/ending at depot."""
    n = len(points)
    # Reindex so depot is 0 internally
    others = [i for i in range(n) if i != depot]
    k = len(others)
    # dp[mask][j] = min cost to start at depot, visit exactly set `mask` of the
    # `others`, and end at others[j] (j bit set in mask).
    INF = float("inf")
    size = 1 << k
    dp = [[INF] * k for _ in range(size)]
    for j in range(k):
        dp[1 << j][j] = _dist(points, depot, others[j])
    for mask in range(size):
        for j in range(k):
            if not (mask & (1 << j)):
                continue
            cur = dp[mask][j]
            if cur == INF:
                continue
            for nxt in range(k):
                if mask & (1 << nxt):
                    continue
                nmask = mask | (1 << nxt)
                cand = cur + _dist(points, others[j], others[nxt])
                if cand < dp[nmask][nxt]:
                    dp[nmask][nxt] = cand
    full = size - 1
    best = INF
    for j in range(k):
        cand = dp[full][j] + _dist(points, others[j], depot)
        if cand < best:
            best = cand
    return best


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()

    inp_path = scratch_dir / INPUT_REL
    if not inp_path.is_file():
        return GradeResult(False, 0.0, f"input {INPUT_REL} not found in scratch dir")

    try:
        inp = json.loads(inp_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse input: {exc}")

    points = inp["points"]
    depot = inp["depot"]
    n = len(points)

    output_path = scratch_dir / OUTPUT_REL
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        agent_output = json.loads(output_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse output JSON: {exc}")

    if not isinstance(agent_output, dict):
        return GradeResult(False, 0.0, "output must be a JSON object")

    for key in ("tour", "tour_length"):
        if key not in agent_output:
            return GradeResult(False, 0.0, f"output missing required key {key!r}")

    tour = agent_output["tour"]
    tl = agent_output["tour_length"]

    if not isinstance(tour, list) or len(tour) != n + 1:
        return GradeResult(False, 0.0, f"tour must be a list of length {n+1}")
    if tour[0] != depot or tour[-1] != depot:
        return GradeResult(False, 0.0, f"tour must start and end at depot ({depot})")
    for v in tour:
        if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v >= n:
            return GradeResult(False, 0.0, f"tour contains invalid index {v!r}")
    middle = tour[1:-1]
    expected = sorted(i for i in range(n) if i != depot)
    if sorted(middle) != expected:
        return GradeResult(False, 0.0, "tour is not a valid Hamiltonian permutation")

    if isinstance(tl, bool) or not isinstance(tl, (int, float)):
        return GradeResult(False, 0.0, "tour_length must be a number")

    computed = 0.0
    for a, b in zip(tour[:-1], tour[1:]):
        computed += _dist(points, a, b)
    if abs(computed - tl) > _TOL * max(1.0, abs(computed)):
        return GradeResult(
            False, 0.0,
            f"declared tour_length {tl} does not match computed {computed}",
        )

    optimal = _optimal_tour_length(points, depot)
    if abs(computed - optimal) > _TOL * max(1.0, abs(optimal)):
        return GradeResult(
            False, 0.0,
            f"tour_length {computed} is not optimal (optimal={optimal})",
        )

    return GradeResult(True, 1.0, f"optimal tour_length={optimal:.6f}")
