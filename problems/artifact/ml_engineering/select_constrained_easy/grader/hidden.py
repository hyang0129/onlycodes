"""Hidden grader for ``ml_engineering__select_constrained_*``.

Continuous F1 grader — the first in the artifact suite. The score is the
F1 of the agent's selected ``run_id`` set against the reference top-20.
``passed`` is reserved for exact set match (F1 == 1.0).

Structural gates (any failure → score = 0.0):

  * file present, header exactly ``run_id,val_acc``
  * exactly 20 data rows
  * each reported ``val_acc`` matches the source ``experiments.csv``
    value within 1e-3 (lenient; agents may rewrite at lower precision)
  * rows sorted by reported ``val_acc`` descending, ``run_id`` ascending
    as tiebreak

Any structural failure yields a 0 with the failure mode named in
``detail``. A structurally valid submission with wrong run_ids gets
``score = F1(run_id_set)``.

Detail always reports P / R / F1 / counts so per-arm error patterns
remain visible in logs even at high scores.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Set, Tuple


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


OUTPUT_REL = "output/selected.csv"
SOURCE_REL = "experiments.csv"
EXPECTED_COLUMNS = ["run_id", "val_acc"]
K_SELECT = 20
VAL_ACC_TOLERANCE = 1e-3

# Constraint set — must match prompt.md and workspace/generator.py.
DATASETS_OK = {"cifar10", "imagenet"}
PARAMS_M_MAX = 50.0
LR_LOW = 1e-5
LR_HIGH = 1e-3
TRAIN_HOURS_MAX = 24.0
DROPOUT_LOW = 0.1
DROPOUT_HIGH = 0.3


def _satisfies(row: Dict[str, str]) -> bool:
    try:
        if row["dataset"] not in DATASETS_OK:
            return False
        if float(row["params_M"]) > PARAMS_M_MAX:
            return False
        lr = float(row["lr"])
        if not (LR_LOW <= lr <= LR_HIGH):
            return False
        if float(row["train_hours"]) > TRAIN_HOURS_MAX:
            return False
        dropout = float(row["dropout"])
        if not (DROPOUT_LOW <= dropout <= DROPOUT_HIGH):
            return False
        return True
    except (KeyError, ValueError):
        return False


def _reference_topk(scratch_dir: Path) -> Tuple[Set[str], Dict[str, float]]:
    """Return (reference run_id set, mapping run_id -> source val_acc).

    The mapping covers ALL rows in the source CSV (not just satisfying
    ones) so val_acc verification can succeed even on agent submissions
    that include violators.
    """
    source_path = scratch_dir / SOURCE_REL
    all_val_acc: Dict[str, float] = {}
    satisfying: list[Tuple[str, float]] = []
    with open(source_path, newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                v = float(row["val_acc"])
            except (KeyError, ValueError):
                continue
            all_val_acc[row["run_id"]] = v
            if _satisfies(row):
                satisfying.append((row["run_id"], v))
    satisfying.sort(key=lambda x: (-x[1], x[0]))
    top = {rid for rid, _ in satisfying[:K_SELECT]}
    return top, all_val_acc


def _parse_agent_output(output_path: Path) -> Tuple[list[Tuple[str, float]], str | None]:
    """Return (list of (run_id, val_acc), error message or None)."""
    try:
        with open(output_path, newline="") as fh:
            reader = csv.reader(fh)
            try:
                header = next(reader)
            except StopIteration:
                return [], "output artifact is empty"
            if header != EXPECTED_COLUMNS:
                return [], (
                    f"column header must be exactly {EXPECTED_COLUMNS}; got {header}"
                )
            rows = list(reader)
    except Exception as exc:
        return [], f"could not parse output: {exc}"

    if len(rows) != K_SELECT:
        return [], f"expected exactly {K_SELECT} data rows; got {len(rows)}"

    parsed: list[Tuple[str, float]] = []
    seen: set[str] = set()
    for i, row in enumerate(rows, start=1):
        if len(row) != 2:
            return [], f"row {i}: expected 2 fields, got {len(row)}"
        rid = row[0].strip()
        if not rid:
            return [], f"row {i}: run_id is empty"
        if rid in seen:
            return [], f"row {i}: duplicate run_id {rid!r}"
        try:
            va = float(row[1])
        except ValueError:
            return [], f"row {i}: val_acc {row[1]!r} is not numeric"
        seen.add(rid)
        parsed.append((rid, va))
    return parsed, None


def _f1(predicted: Set[str], expected: Set[str]) -> Tuple[float, float, float, int, int, int]:
    tp = len(predicted & expected)
    fp = len(predicted - expected)
    fn = len(expected - predicted)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1, tp, fp, fn


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    output_path = scratch_dir / OUTPUT_REL
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    parsed, err = _parse_agent_output(output_path)
    if err is not None:
        return GradeResult(False, 0.0, err)

    expected_set, source_val_acc = _reference_topk(scratch_dir)

    # Structural gate 1: every reported val_acc must match the source within tolerance.
    bad_va = []
    for rid, va in parsed:
        src = source_val_acc.get(rid)
        if src is None:
            bad_va.append((rid, "not in source"))
            continue
        if abs(va - src) > VAL_ACC_TOLERANCE:
            bad_va.append((rid, f"reported {va} vs source {src} (Δ={va - src:+.4f})"))
    if bad_va:
        sample = bad_va[0]
        return GradeResult(
            False, 0.0,
            f"val_acc mismatch on {len(bad_va)} row(s); example: "
            f"{sample[0]} {sample[1]}"
        )

    # Structural gate 2: sort order = val_acc desc, run_id asc tiebreak.
    for i in range(len(parsed) - 1):
        (rid_a, va_a), (rid_b, va_b) = parsed[i], parsed[i + 1]
        if va_a < va_b - 1e-9:
            return GradeResult(
                False, 0.0,
                f"sort order violated at rows {i+1},{i+2}: "
                f"val_acc {va_a} then {va_b} (must be descending)"
            )
        if abs(va_a - va_b) <= 1e-9 and rid_a > rid_b:
            return GradeResult(
                False, 0.0,
                f"tiebreak violated at rows {i+1},{i+2}: "
                f"val_acc tied at {va_a} but run_ids {rid_a!r} > {rid_b!r}"
            )

    # Scoring: F1 on run_id sets.
    predicted_set = {rid for rid, _ in parsed}
    precision, recall, f1, tp, fp, fn = _f1(predicted_set, expected_set)

    passed = f1 == 1.0
    detail = (
        f"F1={f1:.4f} P={precision:.4f} R={recall:.4f} "
        f"(tp={tp} fp={fp} fn={fn})"
    )
    if not passed:
        missing = sorted(expected_set - predicted_set)[:3]
        extra = sorted(predicted_set - expected_set)[:3]
        if missing:
            detail += f"; missing: {missing}"
        if extra:
            detail += f"; extra: {extra}"
    return GradeResult(passed, f1, detail)
