"""Hidden grader for ``data_science__multiclass_metrics_per_class_hard``.

Recomputes per-class precision/recall/F1/support plus macro and weighted
averages, plus accuracy, from ``scratch_dir/predictions.csv`` and compares
the agent's ``output/result.json`` field-by-field. All-or-nothing scoring.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, precision_recall_fscore_support


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


INPUT_CSV = "predictions.csv"
OUTPUT_REL = "output/result.json"
REQUIRED_TOP = {"per_class", "macro_avg", "weighted_avg", "accuracy"}
REQUIRED_PER_CLASS = {"class", "support", "precision", "recall", "f1"}
REQUIRED_AVG = {"precision", "recall", "f1"}
FLOAT_TOL = 1e-4


def _compute_expected(scratch_dir: Path) -> dict:
    df = pd.read_csv(scratch_dir / INPUT_CSV)
    y_true = df["y_true"].to_numpy()
    y_pred = df["y_pred"].to_numpy()
    labels = sorted(int(c) for c in np.unique(y_true))

    p, r, f, s = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, average=None, zero_division=0
    )
    per_class = []
    for i, c in enumerate(labels):
        per_class.append(
            {
                "class": int(c),
                "support": int(s[i]),
                "precision": float(p[i]),
                "recall": float(r[i]),
                "f1": float(f[i]),
            }
        )

    macro_p, macro_r, macro_f, _ = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, average="macro", zero_division=0
    )
    weighted_p, weighted_r, weighted_f, _ = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, average="weighted", zero_division=0
    )
    accuracy = float(accuracy_score(y_true, y_pred))

    return {
        "per_class": per_class,
        "macro_avg": {
            "precision": float(macro_p),
            "recall": float(macro_r),
            "f1": float(macro_f),
        },
        "weighted_avg": {
            "precision": float(weighted_p),
            "recall": float(weighted_r),
            "f1": float(weighted_f),
        },
        "accuracy": accuracy,
    }


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    output_path = scratch_dir / OUTPUT_REL

    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        data = json.loads(output_path.read_text())
    except json.JSONDecodeError as exc:
        return GradeResult(False, 0.0, f"output is not valid JSON: {exc}")

    if not isinstance(data, dict):
        return GradeResult(
            False, 0.0, f"top-level JSON must be an object; got {type(data).__name__}"
        )

    keys = set(data.keys())
    missing = REQUIRED_TOP - keys
    extra = keys - REQUIRED_TOP
    if missing:
        return GradeResult(False, 0.0, f"missing top-level field(s): {sorted(missing)}")
    if extra:
        return GradeResult(False, 0.0, f"unexpected top-level field(s): {sorted(extra)}")

    pc = data["per_class"]
    if not isinstance(pc, list):
        return GradeResult(False, 0.0, "per_class must be a list")
    for i, entry in enumerate(pc):
        if not isinstance(entry, dict):
            return GradeResult(False, 0.0, f"per_class[{i}] must be an object")
        ek = set(entry.keys())
        if ek != REQUIRED_PER_CLASS:
            return GradeResult(
                False,
                0.0,
                f"per_class[{i}] keys {sorted(ek)} != {sorted(REQUIRED_PER_CLASS)}",
            )
        if not isinstance(entry["class"], int) or isinstance(entry["class"], bool):
            return GradeResult(
                False, 0.0, f"per_class[{i}].class must be a non-bool integer"
            )
        if not isinstance(entry["support"], int) or isinstance(entry["support"], bool):
            return GradeResult(
                False, 0.0, f"per_class[{i}].support must be a non-bool integer"
            )
        for fld in ("precision", "recall", "f1"):
            v = entry[fld]
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                return GradeResult(
                    False, 0.0, f"per_class[{i}].{fld} must be a number"
                )

    classes = [e["class"] for e in pc]
    if classes != sorted(classes):
        return GradeResult(False, 0.0, "per_class must be sorted ascending by class")
    if len(set(classes)) != len(classes):
        return GradeResult(False, 0.0, "per_class contains duplicate class labels")

    for avg_key in ("macro_avg", "weighted_avg"):
        avg = data[avg_key]
        if not isinstance(avg, dict):
            return GradeResult(False, 0.0, f"{avg_key} must be an object")
        ak = set(avg.keys())
        if ak != REQUIRED_AVG:
            return GradeResult(
                False, 0.0, f"{avg_key} keys {sorted(ak)} != {sorted(REQUIRED_AVG)}"
            )
        for fld in REQUIRED_AVG:
            v = avg[fld]
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                return GradeResult(
                    False, 0.0, f"{avg_key}.{fld} must be a number"
                )

    acc = data["accuracy"]
    if not isinstance(acc, (int, float)) or isinstance(acc, bool):
        return GradeResult(
            False, 0.0, f"accuracy must be a number; got {type(acc).__name__}"
        )

    expected = _compute_expected(scratch_dir)
    exp_classes = [e["class"] for e in expected["per_class"]]

    if classes != exp_classes:
        got = set(classes)
        ref = set(exp_classes)
        missing_c = sorted(ref - got)
        extra_c = sorted(got - ref)
        bits: list[str] = []
        if missing_c:
            bits.append(f"missing class(es): {missing_c}")
        if extra_c:
            bits.append(f"unexpected class(es): {extra_c}")
        if not bits:
            bits.append("class order must be ascending integer")
        return GradeResult(False, 0.0, "per_class class set mismatch: " + "; ".join(bits))

    for got_entry, exp_entry in zip(pc, expected["per_class"]):
        c = exp_entry["class"]
        if got_entry["support"] != exp_entry["support"]:
            return GradeResult(
                False,
                0.0,
                f"per_class[class={c}].support mismatch: got {got_entry['support']} (incorrect)",
            )
        for fld in ("precision", "recall", "f1"):
            if abs(float(got_entry[fld]) - exp_entry[fld]) > FLOAT_TOL:
                return GradeResult(
                    False,
                    0.0,
                    f"per_class[class={c}].{fld} off by more than {FLOAT_TOL} "
                    "(check: one-vs-rest definitions; "
                    "f1 = 2*p*r/(p+r) per class)",
                )

    for avg_key in ("macro_avg", "weighted_avg"):
        for fld in REQUIRED_AVG:
            if abs(float(data[avg_key][fld]) - expected[avg_key][fld]) > FLOAT_TOL:
                return GradeResult(
                    False,
                    0.0,
                    f"{avg_key}.{fld} off by more than {FLOAT_TOL} "
                    "(check: macro = mean of per-class values; "
                    "weighted = support-weighted mean of per-class values; "
                    "f1 is averaged directly, NOT recomputed from avg P and R)",
                )

    if abs(float(acc) - expected["accuracy"]) > FLOAT_TOL:
        return GradeResult(
            False,
            0.0,
            f"accuracy off by more than {FLOAT_TOL} from "
            "#{i : y_true[i] == y_pred[i]} / N",
        )

    return GradeResult(
        True,
        1.0,
        f"per-class ({len(pc)}) + macro + weighted + accuracy all within ±{FLOAT_TOL}",
    )
