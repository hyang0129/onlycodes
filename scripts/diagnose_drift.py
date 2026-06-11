#!/usr/bin/env python3
"""Thin debug helper: grade one instance's GOLD patch verbatim (#354).

Under verbatim grading there is no in-harness "drift" to root-cause — the official
``run_evaluation`` runs on the unmodified prebuilt image, so a gold patch that
does not resolve is the benchmark's own verdict, not a harness artifact. This
helper just grades the gold patch of each given instance via
:func:`swebench.grading_official.grade_one` and prints the official report plus
where ``run_evaluation`` wrote its per-instance log tree.

    python scripts/diagnose_drift.py <iid> [<iid> ...]

Needs a reachable Docker daemon and network/``HF_TOKEN`` (source ``.env`` first if
you keep a token there). Images already pulled are reused (no re-pull).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # repo root

from swebench import grading_official  # noqa: E402
from scripts.validate_verified_image import _load_gold_patches  # noqa: E402

# run_evaluation log tree: <cwd>/logs/run_evaluation/<run_id>/<model>/<iid>/.
# grade_one uses run_id=gradeone_<iid>, model_name=DEFAULT_MODEL_NAME, and a temp
# cwd; the exact dir is internal, so we point at the conventional relative layout.
_LOG_HINT = "logs/run_evaluation/gradeone_<iid>/{model}/<iid>/ (under grade_one's temp cwd)"


def diagnose(iid: str, gold: dict[str, str]) -> None:
    print(f"\n{'='*78}\n{iid}\n{'='*78}")
    patch = gold.get(iid, "")
    if not patch:
        print("  !! no gold patch on HF for this id")
        return
    report = grading_official.grade_one(iid, patch)
    print("  official report:")
    print(json.dumps(report, indent=2))
    print(f"  resolved = {report.get('resolved')}")
    print("  log tree: " + _LOG_HINT.format(model=grading_official.DEFAULT_MODEL_NAME))


def main() -> None:
    ids = sys.argv[1:]
    if not ids:
        print("usage: diagnose_drift.py <iid> [<iid> ...]")
        sys.exit(1)
    gold = _load_gold_patches(set(ids))
    for iid in ids:
        try:
            diagnose(iid, gold)
        except Exception as e:  # noqa: BLE001 - debug helper, surface everything
            import traceback
            print(f"  !! diagnose raised: {type(e).__name__}: {e}")
            traceback.print_exc()


if __name__ == "__main__":
    main()
