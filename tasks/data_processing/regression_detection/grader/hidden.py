"""Hidden grader for data_processing__regression_detection.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    The agent's output/regressions.jsonl MUST contain exactly the top-3
    endpoints with the largest day-over-day p95 latency regression, identified
    by set membership (order-agnostic). Each row must have:

      - endpoint (string, exact match)
      - regression_score (float, within REL_TOL of the true value)

    "Day-over-day regression" is:
        regression_score = nearest_rank_p95(today_latencies)
                         - nearest_rank_p95(yesterday_latencies)
    where today = 2024-01-15 and yesterday = 2024-01-14.

    The top-3 are selected by descending regression_score. Ties broken by
    endpoint lexicographic order (ascending). Output rows whose regression_score
    is non-positive are always incorrect (regression implies increase).

Determinism: pure function of scratch_dir contents. No clock, no network.
"""
# GRADER-SENTINEL: d5c6fd69-3da6-483c-aaf8-85255815af50

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


OUTPUT_REL = "output/regressions.jsonl"
REQUIRED_KEYS = frozenset({"endpoint", "regression_score"})
YESTERDAY = "2024-01-14"
TODAY = "2024-01-15"
TOP_N = 3
REL_TOL = 0.02   # 2% tolerance on regression_score


def _nearest_rank_p95(values: list[float]) -> float:
    n = len(values)
    if n == 0:
        raise ValueError("empty latency list")
    s = sorted(values)
    k = max(0, math.ceil(0.95 * n) - 1)
    return float(s[min(k, n - 1)])


def _compute_regressions(scratch_dir: Path) -> dict[str, float]:
    """Return {endpoint: regression_score} for every endpoint with data on both days."""
    day_lats: dict[str, dict[str, list[float]]] = {YESTERDAY: {}, TODAY: {}}

    for day in (YESTERDAY, TODAY):
        bucket = day_lats[day]
        for f in sorted(scratch_dir.glob(f"metrics_{day}_*.jsonl")):
            for line in f.read_text().splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                ep = row["endpoint"]
                bucket.setdefault(ep, []).append(float(row["latency_ms"]))

    regressions: dict[str, float] = {}
    all_eps = set(day_lats[YESTERDAY]) & set(day_lats[TODAY])
    for ep in all_eps:
        p95_y = _nearest_rank_p95(day_lats[YESTERDAY][ep])
        p95_t = _nearest_rank_p95(day_lats[TODAY][ep])
        regressions[ep] = p95_t - p95_y
    return regressions


def _top_n(regressions: dict[str, float], n: int) -> list[tuple[str, float]]:
    """Return top-n by regression_score desc, ties broken by endpoint asc."""
    ranked = sorted(regressions.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranked[:n]


def grade(scratch_dir: Path) -> GradeResult:  # noqa: C901
    scratch_dir = Path(scratch_dir).resolve()
    output_path = scratch_dir / OUTPUT_REL

    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    raw = output_path.read_text()
    if not raw.strip():
        return GradeResult(False, 0.0, "output artifact is empty")

    agent_rows: list[dict] = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            return GradeResult(False, 0.0, f"line {lineno}: JSON parse error: {exc.msg}")
        if not isinstance(row, dict):
            return GradeResult(False, 0.0, f"line {lineno}: row is not an object")
        keys = set(row.keys())
        if keys != REQUIRED_KEYS:
            missing = REQUIRED_KEYS - keys
            extra = keys - REQUIRED_KEYS
            bits = []
            if missing:
                bits.append(f"missing {sorted(missing)}")
            if extra:
                bits.append(f"extra {sorted(extra)}")
            return GradeResult(False, 0.0, f"line {lineno}: {'; '.join(bits)}")
        agent_rows.append(row)

    if len(agent_rows) != TOP_N:
        return GradeResult(
            False, 0.0,
            f"expected exactly {TOP_N} rows, got {len(agent_rows)}",
        )

    # Compute ground truth
    try:
        regressions = _compute_regressions(scratch_dir)
    except Exception as exc:
        return GradeResult(False, 0.0, f"grader error computing regressions: {exc}")

    true_top = {ep for ep, _ in _top_n(regressions, TOP_N)}
    true_scores = dict(_top_n(regressions, TOP_N))

    agent_eps: set[str] = set()
    for i, row in enumerate(agent_rows, start=1):
        ep = row["endpoint"]
        if not isinstance(ep, str):
            return GradeResult(False, 0.0, f"row {i}: endpoint must be a string")
        if ep in agent_eps:
            return GradeResult(False, 0.0, f"row {i}: duplicate endpoint {ep!r}")
        agent_eps.add(ep)

    # Set membership check (order-agnostic)
    missing_eps = sorted(true_top - agent_eps)
    wrong_eps = sorted(agent_eps - true_top)
    if missing_eps or wrong_eps:
        parts = []
        if missing_eps:
            parts.append(f"missing correct endpoint(s): {missing_eps}")
        if wrong_eps:
            parts.append(f"incorrect endpoint(s) in output: {wrong_eps}")
        return GradeResult(False, 0.0, "; ".join(parts))

    # Regression_score tolerance check
    bad: list[str] = []
    for row in agent_rows:
        ep = row["endpoint"]
        score = row["regression_score"]
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            return GradeResult(False, 0.0, f"{ep}: regression_score must be a number")
        if not math.isfinite(score):
            return GradeResult(False, 0.0, f"{ep}: regression_score is not finite")
        true_score = true_scores[ep]
        abs_err = abs(float(score) - true_score)
        if abs_err > REL_TOL * abs(true_score) + 0.5:
            bad.append(f"{ep}(got {score:.1f}, want ~{true_score:.1f})")

    if bad:
        return GradeResult(
            False, 0.0,
            f"regression_score out of tolerance on {len(bad)} row(s): {bad}",
        )

    return GradeResult(True, 1.0, f"correct top-{TOP_N} regressions identified")
