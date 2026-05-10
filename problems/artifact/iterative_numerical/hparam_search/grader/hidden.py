"""Hidden grader for iterative_numerical__hparam_search.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See
``docs/SCHEMA_ARTIFACT.md`` §3.

Correctness criterion:

    The agent's ``output/result.json`` MUST report hyperparameters
    (``learning_rate``, ``hidden_size``, ``dropout``) such that when
    ``evaluate(lr, hs, do)`` is called with these values, the returned
    accuracy is ``>= ACCURACY_TARGET`` (0.90).

    The grader re-evaluates the toy model on the reported params — agents
    cannot hallucinate high accuracy without actually finding good params.

Per issue #168 the Gaussian peak locations are derived from
``sha256(INSTANCE_ID)`` rather than living as literal constants in source.
The grader mirrors the derivation in ``workspace/generator.py``, so the
grader stays independent of the materialized ``calibration.bin``.

Determinism: the toy model is a deterministic pure-Python function and the
peak-derivation RNG is seeded from a constant, so ``grade()`` is
reproducible.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


OUTPUT_REL = "output/result.json"
ACCURACY_TARGET = 0.90
INSTANCE_ID = "iterative_numerical__hparam_search"


def _seed_for_instance(instance_id: str) -> int:
    """Mirror of ``swebench.artifact_materialize._seed_for_instance``."""
    digest = hashlib.sha256(instance_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _derive_peaks(instance_id: str) -> tuple[float, int, float]:
    """Mirror of ``workspace/generator.derive_peaks`` — keep in lockstep."""
    rng = random.Random(_seed_for_instance(instance_id))
    lr_peak = 10 ** rng.uniform(math.log10(3e-4), math.log10(5e-2))
    hs_peak = 8 * rng.randint(4, 48)
    do_peak = rng.uniform(0.10, 0.60)
    return lr_peak, hs_peak, do_peak


_LR_PEAK, _HS_PEAK, _DO_PEAK = _derive_peaks(INSTANCE_ID)


def _evaluate(learning_rate: float, hidden_size: int, dropout: float) -> float:
    """Mirror of ``workspace/toy_model.py:evaluate`` — kept in sync (issue #168)."""
    lr_score = math.exp(-3.0 * (math.log10(learning_rate / _LR_PEAK)) ** 2)
    hs_score = math.exp(-((hidden_size - _HS_PEAK) / 128.0) ** 2)
    do_score = math.exp(-((dropout - _DO_PEAK) / 0.2) ** 2)
    return round(0.95 * lr_score * hs_score * do_score, 6)


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    output_path = scratch_dir / OUTPUT_REL

    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        agent_output = json.loads(output_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse output JSON: {exc}")

    if not isinstance(agent_output, dict):
        return GradeResult(False, 0.0, "output must be a JSON object")

    for key in ("learning_rate", "hidden_size", "dropout"):
        if key not in agent_output:
            return GradeResult(False, 0.0, f"output missing required key '{key}'")

    lr = agent_output["learning_rate"]
    hs = agent_output["hidden_size"]
    do = agent_output["dropout"]

    if not isinstance(lr, (int, float)) or isinstance(lr, bool):
        return GradeResult(False, 0.0, "learning_rate must be a number")
    if not isinstance(hs, int) or isinstance(hs, bool):
        return GradeResult(False, 0.0, "hidden_size must be an integer")
    if not isinstance(do, (int, float)) or isinstance(do, bool):
        return GradeResult(False, 0.0, "dropout must be a number")

    if lr <= 0 or not math.isfinite(lr):
        return GradeResult(False, 0.0, f"learning_rate must be positive finite, got {lr}")
    if hs <= 0:
        return GradeResult(False, 0.0, f"hidden_size must be positive, got {hs}")
    if not (0.0 <= do <= 1.0):
        return GradeResult(False, 0.0, f"dropout must be in [0,1], got {do}")

    # Re-evaluate on the reported params (catches hallucinated accuracy)
    actual_accuracy = _evaluate(float(lr), int(hs), float(do))

    if actual_accuracy < ACCURACY_TARGET:
        return GradeResult(
            False,
            round(actual_accuracy / ACCURACY_TARGET, 4),
            f"accuracy {actual_accuracy:.4f} < target {ACCURACY_TARGET} "
            f"(lr={lr}, hs={hs}, dropout={do})",
        )

    return GradeResult(
        True, 1.0,
        f"accuracy {actual_accuracy:.4f} ≥ target {ACCURACY_TARGET} "
        f"(lr={lr}, hs={hs}, dropout={do})",
    )
