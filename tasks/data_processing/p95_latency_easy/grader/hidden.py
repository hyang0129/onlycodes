"""Hidden grader for data_processing__p95_latency_easy.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    For every non-/health* endpoint in workspace/access.jsonl, the agent's
    output/p95.jsonl MUST contain exactly one row with:

      - the correct endpoint string (exact match),
      - a p95_ms value within REL_TOL relative tolerance (or ABS_TOL absolute
        tolerance) of the ground-truth p95 computed by this grader using the
        nearest-rank definition described in prompt.md,
      - a count equal to the number of that endpoint's rows in the input.

    Any row referencing a /health* endpoint fails the task.
    Any missing or duplicate endpoint fails the task.
    Any extra or missing keys fail the task.

Determinism: pure function of scratch_dir contents. No clock, no network, no
unseeded randomness. (No randomness is used at all; the identity comes from
instance_id if ever needed — see SCHEMA §3.2.3.)
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

# NOTE: we intentionally do NOT import from swebench.artifact_models here.
# The grader should be runnable standalone under tools/verify_graders.py or
# any ad-hoc harness; the harness uses structural typing (SCHEMA §3.1), so a
# local dataclass with passed/score/detail is sufficient.


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


INPUT_REL = "access.jsonl"          # resolved under scratch_dir (workspace was copied in)
OUTPUT_REL = "output/p95.jsonl"     # agent writes here, per task.yaml

REQUIRED_KEYS = frozenset({"endpoint", "p95_ms", "count"})

# Tolerance: tight enough that "all zeros" and "off by > 5%" both fail, loose
# enough to absorb rounding to 3 decimal places (see prompt.md).
REL_TOL = 0.01      # 1%
ABS_TOL = 0.01      # 0.01 ms floor for very small latencies


def _nearest_rank_p95(values: list[float]) -> float:
    """Nearest-rank p95, per prompt.md: sorted[ceil(0.95*n)-1], clamped to [0,n-1]."""
    n = len(values)
    if n == 0:
        raise ValueError("empty latency list")
    s = sorted(values)
    k = math.ceil(0.95 * n) - 1
    if k < 0:
        k = 0
    if k >= n:
        k = n - 1
    return float(s[k])


def _compute_ground_truth(access_path: Path) -> dict[str, tuple[float, int]]:
    """Return {endpoint: (p95_ms, count)} for every non-/health* endpoint."""
    buckets: dict[str, list[float]] = {}
    with open(access_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            ep = row["endpoint"]
            if ep.startswith("/health"):
                continue
            buckets.setdefault(ep, []).append(float(row["latency_ms"]))
    return {ep: (_nearest_rank_p95(lats), len(lats)) for ep, lats in buckets.items()}


def grade(scratch_dir: Path) -> GradeResult:  # noqa: C901 — single entrypoint
    scratch_dir = Path(scratch_dir).resolve()
    access_path = scratch_dir / INPUT_REL
    output_path = scratch_dir / OUTPUT_REL

    if not access_path.is_file():
        return GradeResult(
            passed=False,
            score=0.0,
            detail=f"input {INPUT_REL} not found in scratch dir (grader cannot "
                   "recompute ground truth)",
        )
    if not output_path.is_file():
        return GradeResult(
            passed=False,
            score=0.0,
            detail="output artifact not produced",
        )

    # Parse agent output
    try:
        raw = output_path.read_text()
    except OSError as exc:
        return GradeResult(False, 0.0, f"could not read output artifact: {exc}")
    if not raw.strip():
        return GradeResult(False, 0.0, "output artifact is empty")

    agent_rows: list[dict] = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            return GradeResult(
                False, 0.0,
                f"output artifact failed to parse at line {lineno}: {exc.msg}",
            )
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

    if not agent_rows:
        return GradeResult(False, 0.0, "output contains no rows")

    # Check no /health* leaked, no duplicates
    seen: set[str] = set()
    for i, row in enumerate(agent_rows, start=1):
        ep = row["endpoint"]
        if not isinstance(ep, str):
            return GradeResult(False, 0.0, f"row {i}: endpoint must be a string")
        if ep.startswith("/health"):
            return GradeResult(
                False, 0.0,
                f"row {i}: endpoint {ep!r} is a /health* probe and must be "
                "excluded from the output",
            )
        if ep in seen:
            return GradeResult(
                False, 0.0,
                f"row {i}: duplicate endpoint {ep!r}",
            )
        seen.add(ep)

    # Ground truth
    truth = _compute_ground_truth(access_path)

    # Coverage: every non-/health* endpoint in the input must be present.
    missing_endpoints = sorted(set(truth.keys()) - seen)
    if missing_endpoints:
        return GradeResult(
            False, 0.0,
            f"missing {len(missing_endpoints)} endpoint(s): "
            f"{missing_endpoints[:3]}"
            + (" ..." if len(missing_endpoints) > 3 else ""),
        )
    unexpected = sorted(seen - set(truth.keys()))
    if unexpected:
        return GradeResult(
            False, 0.0,
            f"{len(unexpected)} unexpected endpoint(s) in output: {unexpected[:3]}"
            + (" ..." if len(unexpected) > 3 else ""),
        )

    # Value check: p95 within tolerance, count exact.
    bad_p95: list[str] = []
    bad_count: list[str] = []
    bad_type: list[str] = []

    for row in agent_rows:
        ep = row["endpoint"]
        true_p95, true_count = truth[ep]

        p95 = row["p95_ms"]
        if isinstance(p95, bool) or not isinstance(p95, (int, float)):
            bad_type.append(f"{ep}: p95_ms type {type(p95).__name__}")
            continue
        if not math.isfinite(p95):
            bad_type.append(f"{ep}: p95_ms not finite")
            continue

        count = row["count"]
        if isinstance(count, bool) or not isinstance(count, int):
            bad_type.append(f"{ep}: count type {type(count).__name__}")
            continue

        abs_err = abs(float(p95) - true_p95)
        if abs_err > ABS_TOL and abs_err > REL_TOL * true_p95:
            bad_p95.append(ep)
        if count != true_count:
            bad_count.append(f"{ep}(got {count}, want {true_count})")

    if bad_type:
        return GradeResult(
            False, 0.0,
            f"type error(s) in {len(bad_type)} row(s): {bad_type[:2]}",
        )
    if bad_p95 or bad_count:
        parts = []
        if bad_p95:
            parts.append(
                f"p95 off (>{REL_TOL*100:.1f}%) on {len(bad_p95)}/{len(truth)} "
                f"endpoints: {bad_p95[:3]}"
                + (" ..." if len(bad_p95) > 3 else "")
            )
        if bad_count:
            parts.append(
                f"count mismatch on {len(bad_count)} endpoint(s): {bad_count[:2]}"
            )
        return GradeResult(False, 0.0, "; ".join(parts))

    return GradeResult(
        True, 1.0,
        f"all {len(truth)} endpoint(s) within tolerance",
    )
