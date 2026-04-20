"""Hidden grader for iterative_numerical__exp_decay_fit.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    The agent's output/params.json MUST contain A, k, C parameters such that
    the model y = A * exp(-k * t) + C has RMSE < RMSE_THRESHOLD on the
    provided data.jsonl points.

    RMSE_THRESHOLD = 1.0 ms (about 3× the data noise floor of ~0.35).
    Parameters of all-zero or random values will have RMSE >> threshold.

Determinism: pure function of scratch_dir/data.jsonl contents.
"""
# GRADER-SENTINEL: 32ae948a-f0ed-496a-96c3-4c6d3f17fc56

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


INPUT_REL = "data.jsonl"
OUTPUT_REL = "output/params.json"
RMSE_THRESHOLD = 1.0


def _compute_rmse(A, k, C, data: list[dict]) -> float:
    sse = sum((p["y"] - (A * math.exp(-k * p["t"]) + C))**2 for p in data)
    return math.sqrt(sse / len(data))


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()

    input_path = scratch_dir / INPUT_REL
    if not input_path.is_file():
        return GradeResult(False, 0.0, f"input {INPUT_REL} not found in scratch dir")

    data = [json.loads(line) for line in input_path.read_text().splitlines() if line.strip()]
    if not data:
        return GradeResult(False, 0.0, "data.jsonl is empty")

    output_path = scratch_dir / OUTPUT_REL
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        agent_output = json.loads(output_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse output JSON: {exc}")

    if not isinstance(agent_output, dict):
        return GradeResult(False, 0.0, "output must be a JSON object")

    for key in ("A", "k", "C"):
        if key not in agent_output:
            return GradeResult(False, 0.0, f"output missing required key '{key}'")
        v = agent_output[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return GradeResult(False, 0.0, f"'{key}' must be a number, got {type(v).__name__}")
        if not math.isfinite(v):
            return GradeResult(False, 0.0, f"'{key}' must be finite, got {v}")

    A = float(agent_output["A"])
    k = float(agent_output["k"])
    C = float(agent_output["C"])

    if k <= 0:
        return GradeResult(False, 0.0, f"k must be positive (decay rate), got {k}")

    try:
        rmse = _compute_rmse(A, k, C, data)
    except Exception as exc:
        return GradeResult(False, 0.0, f"error computing RMSE: {exc}")

    if not math.isfinite(rmse):
        return GradeResult(False, 0.0, f"RMSE is not finite (A={A}, k={k}, C={C})")

    if rmse >= RMSE_THRESHOLD:
        return GradeResult(
            False, 0.0,
            f"RMSE {rmse:.4f} ≥ threshold {RMSE_THRESHOLD} "
            f"(A={A:.4f}, k={k:.4f}, C={C:.4f})",
        )

    return GradeResult(
        True, 1.0,
        f"RMSE {rmse:.4f} < threshold {RMSE_THRESHOLD} "
        f"(A={A:.4f}, k={k:.4f}, C={C:.4f})",
    )
