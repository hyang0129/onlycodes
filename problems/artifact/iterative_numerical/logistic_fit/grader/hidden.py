"""Hidden grader for iterative_numerical__logistic_fit.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    output/params.json provides L, k, x0 such that the RMSE of the
    3-parameter logistic model against signups.jsonl is below
    RMSE_THRESHOLD. L > 0 and k > 0 are required.

Determinism: pure function of scratch_dir contents.
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


INPUT_REL = "signups.jsonl"
OUTPUT_REL = "output/params.json"
RMSE_THRESHOLD = 5.0


def _model(L: float, k: float, x0: float, x: float) -> float:
    # Numerically stable logistic
    z = -k * (x - x0)
    if z >= 0:
        ez = math.exp(-z)
        return L * ez / (1.0 + ez) if False else L / (1.0 + math.exp(z))
    # z < 0 -> exp(z) small, safe
    return L / (1.0 + math.exp(z))


def _rmse(L: float, k: float, x0: float, data: list[dict]) -> float:
    sse = 0.0
    for p in data:
        yhat = _model(L, k, x0, float(p["x"]))
        sse += (float(p["y"]) - yhat) ** 2
    return math.sqrt(sse / len(data))


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()

    input_path = scratch_dir / INPUT_REL
    if not input_path.is_file():
        return GradeResult(False, 0.0, f"input {INPUT_REL} not found in scratch dir")

    data = [json.loads(line) for line in input_path.read_text().splitlines() if line.strip()]
    if not data:
        return GradeResult(False, 0.0, "signups.jsonl is empty")

    output_path = scratch_dir / OUTPUT_REL
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        agent_output = json.loads(output_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse output JSON: {exc}")

    if not isinstance(agent_output, dict):
        return GradeResult(False, 0.0, "output must be a JSON object")

    for key in ("L", "k", "x0"):
        if key not in agent_output:
            return GradeResult(False, 0.0, f"output missing required key '{key}'")
        v = agent_output[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return GradeResult(False, 0.0, f"'{key}' must be a number, got {type(v).__name__}")
        if not math.isfinite(v):
            return GradeResult(False, 0.0, f"'{key}' must be finite, got {v}")

    L = float(agent_output["L"])
    k = float(agent_output["k"])
    x0 = float(agent_output["x0"])

    if L <= 0:
        return GradeResult(False, 0.0, f"L must be positive (carrying capacity), got {L}")
    if k <= 0:
        return GradeResult(False, 0.0, f"k must be positive (growth rate), got {k}")

    try:
        rmse = _rmse(L, k, x0, data)
    except (OverflowError, ValueError) as exc:
        return GradeResult(False, 0.0, f"error computing RMSE: {exc}")

    if not math.isfinite(rmse):
        return GradeResult(False, 0.0, f"RMSE is not finite (L={L}, k={k}, x0={x0})")

    if rmse >= RMSE_THRESHOLD:
        return GradeResult(
            False, 0.0,
            f"RMSE {rmse:.4f} >= threshold {RMSE_THRESHOLD} "
            f"(L={L:.4f}, k={k:.4f}, x0={x0:.4f})",
        )

    return GradeResult(
        True, 1.0,
        f"RMSE {rmse:.4f} < threshold {RMSE_THRESHOLD} "
        f"(L={L:.4f}, k={k:.4f}, x0={x0:.4f})",
    )
