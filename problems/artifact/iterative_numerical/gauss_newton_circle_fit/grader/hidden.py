"""Hidden grader for iterative_numerical__gauss_newton_circle_fit.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    output/circle.json provides (cx, cy, r) with r > 0 such that the RMS of
    the geometric residuals
        r_i = sqrt((u_i - cx)^2 + (v_i - cy)^2) - r
    evaluated over points.jsonl is strictly below RMS_THRESHOLD.

Determinism: pure arithmetic on scratch_dir contents.
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


INPUT_REL = "points.jsonl"
OUTPUT_REL = "output/circle.json"
RMS_THRESHOLD = 0.08


def _rms_residual(cx: float, cy: float, r: float, pts: list[dict]) -> float:
    sse = 0.0
    for p in pts:
        du = float(p["u"]) - cx
        dv = float(p["v"]) - cy
        d = math.sqrt(du * du + dv * dv)
        sse += (d - r) ** 2
    return math.sqrt(sse / len(pts))


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()

    input_path = scratch_dir / INPUT_REL
    if not input_path.is_file():
        return GradeResult(False, 0.0, f"input {INPUT_REL} not found in scratch dir")

    pts = [json.loads(line) for line in input_path.read_text().splitlines() if line.strip()]
    if not pts:
        return GradeResult(False, 0.0, "points.jsonl is empty")

    output_path = scratch_dir / OUTPUT_REL
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        agent = json.loads(output_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse output JSON: {exc}")

    if not isinstance(agent, dict):
        return GradeResult(False, 0.0, "output must be a JSON object")

    for key in ("cx", "cy", "r"):
        if key not in agent:
            return GradeResult(False, 0.0, f"output missing required key '{key}'")
        v = agent[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return GradeResult(False, 0.0, f"'{key}' must be a number, got {type(v).__name__}")
        if not math.isfinite(v):
            return GradeResult(False, 0.0, f"'{key}' must be finite, got {v}")

    cx = float(agent["cx"])
    cy = float(agent["cy"])
    r = float(agent["r"])

    if r <= 0:
        return GradeResult(False, 0.0, f"r must be positive, got {r}")

    rms = _rms_residual(cx, cy, r, pts)
    if not math.isfinite(rms):
        return GradeResult(False, 0.0, f"RMS residual not finite (cx={cx}, cy={cy}, r={r})")

    if rms >= RMS_THRESHOLD:
        return GradeResult(
            False, 0.0,
            f"RMS residual {rms:.4f} >= threshold {RMS_THRESHOLD} "
            f"(cx={cx:.4f}, cy={cy:.4f}, r={r:.4f})",
        )

    return GradeResult(
        True, 1.0,
        f"RMS residual {rms:.4f} < threshold {RMS_THRESHOLD} "
        f"(cx={cx:.4f}, cy={cy:.4f}, r={r:.4f})",
    )
