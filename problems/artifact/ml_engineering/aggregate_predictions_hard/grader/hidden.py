"""Hidden grader for ml_engineering__aggregate_predictions_{easy,medium,hard}.

Scores the agent's ``output/predictions.csv`` by comparing each row against
the committed reference.

    score = correct_rows / total_reference_rows

A row is "correct" when the agent's ``pred_prob`` for that ``id`` is within
``1e-4`` absolute tolerance of the reference value.  Extra IDs in the agent
output are ignored.  Missing IDs count as wrong.  Duplicate IDs in the agent
output are deduplicated by taking the first occurrence.

``passed`` is True only when ``score == 1.0``.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

_REF_PATH = Path(__file__).parent / "reference_output.csv"
_TOLERANCE = 1e-4


def _load_csv(path: Path) -> dict[str, float]:
    """Load an id->pred_prob mapping from a CSV file.

    Returns empty dict if the file cannot be parsed.
    Duplicate IDs: first occurrence wins.
    """
    result: dict[str, float] = {}
    try:
        with open(path, newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                sid = row.get("id", "").strip()
                if not sid or sid in result:
                    continue
                try:
                    result[sid] = float(row["pred_prob"])
                except (KeyError, ValueError):
                    continue
    except Exception:
        pass
    return result


def grade(scratch_dir: str) -> "GradeResult":  # noqa: F821
    sys.path.insert(0, str(Path(__file__).parents[4]))
    from swebench.artifact_models import GradeResult  # type: ignore

    output_path = Path(scratch_dir) / "output" / "predictions.csv"

    if not output_path.is_file():
        return GradeResult(passed=False, score=0.0,
                           detail="output/predictions.csv not found")

    reference = _load_csv(_REF_PATH)
    if not reference:
        return GradeResult(passed=False, score=0.0,
                           detail="internal error: could not load reference")

    agent = _load_csv(output_path)
    if not agent:
        return GradeResult(passed=False, score=0.0,
                           detail="output/predictions.csv is empty or unparseable")

    correct = 0
    wrong = 0
    missing = 0

    for sid, ref_prob in reference.items():
        agent_prob = agent.get(sid)
        if agent_prob is None:
            missing += 1
        elif abs(agent_prob - ref_prob) <= _TOLERANCE:
            correct += 1
        else:
            wrong += 1

    total = len(reference)
    score = correct / total
    passed = score == 1.0
    detail = (
        f"{correct}/{total} predictions correct (tol=1e-4); "
        f"missing={missing}, wrong={wrong}"
    )
    return GradeResult(passed=passed, score=score, detail=detail)
