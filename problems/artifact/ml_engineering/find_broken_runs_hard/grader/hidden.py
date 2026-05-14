"""Hidden grader for ``ml_engineering__find_broken_runs_*``.

Recomputes the expected broken set from the JSONL files in
``scratch_dir/runs/`` and compares it against the agent's
``output/broken.csv`` as exact-set match on (run_id, failure_mode) tuples.

A run file is classified as one of:

  * ``healthy``   — last line is a valid JSON object with ``event == "done"``.
  * ``nan``       — contains the bareword ``NaN`` somewhere; no ``done`` event.
  * ``diverged``  — last line is valid JSON; no ``done`` event; the last
                    ~20 step lines show monotonically increasing ``val_loss``
                    that ends above 1e3 while remaining finite.
  * ``truncated`` — anything else without a ``done`` event (last line
                    unparseable, or short file without a divergence ramp).

Only broken runs appear in the agent's output. The grader's ``detail``
string always reports precision/recall/F1 so that partial-recovery
behavior is visible in logs even when the score is 0.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Set, Tuple


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


OUTPUT_REL = "output/broken.csv"
RUNS_REL = "runs"
EXPECTED_COLUMNS = ["run_id", "failure_mode"]
VALID_MODES = {"nan", "truncated", "diverged"}
DIVERGENCE_THRESHOLD = 1_000.0
DIVERGENCE_WINDOW = 20


def _classify_run(path: Path) -> str:
    """Return one of ``healthy``, ``nan``, ``truncated``, ``diverged``."""
    text = path.read_text()
    lines = text.splitlines()
    if not lines:
        return "truncated"

    # Healthy: last line is a `done` event.
    try:
        last_obj = json.loads(lines[-1])
        if isinstance(last_obj, dict) and last_obj.get("event") == "done":
            return "healthy"
        last_parsed = True
    except json.JSONDecodeError:
        last_parsed = False

    # Bareword NaN anywhere in the file → nan.
    if "NaN" in text:
        return "nan"

    if not last_parsed:
        return "truncated"

    # Last line parsed but not `done` → divergence check on the trailing window.
    tail_vals = []
    for ln in lines[-DIVERGENCE_WINDOW:]:
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "val_loss" in obj:
            tail_vals.append(obj["val_loss"])
    if len(tail_vals) >= 2:
        monotone = all(b > a for a, b in zip(tail_vals, tail_vals[1:]))
        if monotone and tail_vals[-1] > DIVERGENCE_THRESHOLD:
            return "diverged"
    return "truncated"


def _expected_broken(scratch_dir: Path) -> Set[Tuple[str, str]]:
    runs_dir = scratch_dir / RUNS_REL
    expected: Set[Tuple[str, str]] = set()
    for run_path in sorted(runs_dir.glob("*.jsonl")):
        mode = _classify_run(run_path)
        if mode != "healthy":
            expected.add((run_path.stem, mode))
    return expected


def _parse_agent_output(output_path: Path) -> Tuple[Set[Tuple[str, str]], str | None]:
    """Return (set of (run_id, mode), error message or None)."""
    try:
        with open(output_path, newline="") as fh:
            reader = csv.reader(fh)
            try:
                header = next(reader)
            except StopIteration:
                return set(), "output artifact is empty"
            if header != EXPECTED_COLUMNS:
                return set(), (
                    f"column header must be exactly {EXPECTED_COLUMNS} in that "
                    f"order; got {header}"
                )
            rows = list(reader)
    except Exception as exc:
        return set(), f"could not parse output: {exc}"

    seen: Dict[str, str] = {}
    for i, row in enumerate(rows, start=1):
        if len(row) != 2:
            return set(), f"row {i}: expected 2 fields, got {len(row)}"
        run_id, mode = row[0].strip(), row[1].strip()
        if not run_id:
            return set(), f"row {i}: run_id is empty"
        if mode not in VALID_MODES:
            return set(), (
                f"row {i}: failure_mode {mode!r} not in {sorted(VALID_MODES)}"
            )
        if run_id in seen:
            return set(), f"row {i}: duplicate run_id {run_id!r}"
        seen[run_id] = mode
    return {(rid, m) for rid, m in seen.items()}, None


def _prf(predicted: Set, expected: Set) -> Tuple[float, float, float]:
    tp = len(predicted & expected)
    fp = len(predicted - expected)
    fn = len(expected - predicted)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    output_path = scratch_dir / OUTPUT_REL
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    predicted, err = _parse_agent_output(output_path)
    expected = _expected_broken(scratch_dir)

    if err is not None:
        precision, recall, f1 = _prf(predicted, expected)
        return GradeResult(
            False, 0.0,
            f"{err} (so far: P={precision:.3f} R={recall:.3f} F1={f1:.3f} "
            f"vs {len(expected)} expected)"
        )

    precision, recall, f1 = _prf(predicted, expected)
    if predicted == expected:
        return GradeResult(
            True, 1.0,
            f"matched {len(expected)} broken runs exactly "
            f"(P={precision:.3f} R={recall:.3f} F1={f1:.3f})"
        )

    missing = sorted(expected - predicted)[:5]
    extra = sorted(predicted - expected)[:5]
    parts = [
        f"set mismatch: predicted {len(predicted)} broken, expected {len(expected)}",
        f"P={precision:.3f} R={recall:.3f} F1={f1:.3f}",
    ]
    if missing:
        parts.append(f"missing example: {missing[0]}")
    if extra:
        parts.append(f"extra example: {extra[0]}")
    return GradeResult(False, 0.0, "; ".join(parts))
