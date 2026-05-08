#!/usr/bin/env python3
"""Smoke test for ``logistic_fit`` grader's ``_model`` numerical stability.

Issue #170 fixed a dead-branch bug in
``problems/artifact/iterative_numerical/logistic_fit/grader/hidden.py``
where an ``if False`` toggle made the stable branch unreachable, causing
``math.exp`` overflow on extreme parameter values. The grader treated the
overflow as an agent failure rather than a grader bug.

This script exercises ``_model`` at a battery of extreme ``(L, k, x0, x)``
inputs and asserts:

  * no exception is raised, AND
  * the returned value is finite, AND
  * the returned value lies in ``[0, L]`` (the model's mathematical range).

Exit codes:
  0 — every case passed
  1 — at least one case raised, returned non-finite, or fell outside [0, L]
  2 — could not load the grader module (path/permissions issue)

Usage:
    python tools/check_logistic_fit_model.py
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path
from typing import Iterable, NamedTuple

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GRADER_PATH = (
    _REPO_ROOT
    / "problems"
    / "artifact"
    / "iterative_numerical"
    / "logistic_fit"
    / "grader"
    / "hidden.py"
)


class Case(NamedTuple):
    name: str
    L: float
    k: float
    x0: float
    x: float


def _extreme_cases() -> Iterable[Case]:
    """Cases that historically tripped the dead-branch overflow bug.

    Each case targets a specific failure mode: very large ``k * (x - x0)``
    in either sign, very far-apart ``x`` and ``x0``, and the boundary
    ``z == 0``.
    """
    return [
        Case("z_very_positive", L=100.0, k=10.0, x0=0.0, x=1000.0),
        Case("z_very_negative", L=100.0, k=10.0, x0=1000.0, x=0.0),
        Case("z_huge_positive", L=1.0, k=1.0, x0=0.0, x=10_000.0),
        Case("z_huge_negative", L=1.0, k=1.0, x0=10_000.0, x=0.0),
        Case("k_extreme_positive", L=1.0, k=1e6, x0=0.0, x=1.0),
        Case("k_extreme_with_negative_z", L=1.0, k=1e6, x0=1.0, x=0.0),
        Case("zero_z", L=1.0, k=1.0, x0=0.0, x=0.0),
        Case("modest_signal", L=200.0, k=0.4, x0=15.0, x=20.0),
        Case("L_large_z_extreme", L=1e9, k=10.0, x0=0.0, x=1000.0),
        Case("L_large_z_extreme_neg", L=1e9, k=10.0, x0=1000.0, x=0.0),
    ]


def _load_model():
    """Load ``_model`` from the grader module by file path.

    The grader directory is not on ``sys.path`` and the grader itself is
    intentionally hidden from agent runs, so we use ``importlib`` rather
    than a normal import. We register the module in ``sys.modules`` before
    ``exec_module`` so that the grader's ``@dataclass`` decorator can
    resolve forward type references (``dataclasses`` looks up the
    decorated class's module via ``sys.modules`` and would otherwise hit
    ``AttributeError: 'NoneType' object has no attribute '__dict__'``).
    """
    if not _GRADER_PATH.is_file():
        raise FileNotFoundError(f"grader module not found: {_GRADER_PATH}")
    module_name = "_logistic_fit_grader_for_smoke_test"
    spec = importlib.util.spec_from_file_location(module_name, _GRADER_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover — defensive
        raise ImportError(f"could not build spec for {_GRADER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    if not hasattr(module, "_model"):
        raise AttributeError("grader module does not define _model")
    return module._model


def main(argv: list[str] | None = None) -> int:
    del argv  # unused; the smoke test takes no arguments today
    try:
        model = _load_model()
    except (FileNotFoundError, ImportError, AttributeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    failed = 0
    for case in _extreme_cases():
        try:
            y = model(case.L, case.k, case.x0, case.x)
        except Exception as exc:  # noqa: BLE001 — surface anything
            print(
                f"FAIL {case.name}: raised {type(exc).__name__}: {exc} "
                f"(L={case.L}, k={case.k}, x0={case.x0}, x={case.x})",
                file=sys.stderr,
            )
            failed += 1
            continue

        if not math.isfinite(y):
            print(
                f"FAIL {case.name}: non-finite return {y!r} "
                f"(L={case.L}, k={case.k}, x0={case.x0}, x={case.x})",
                file=sys.stderr,
            )
            failed += 1
            continue

        # The logistic is bounded by [0, L] for L > 0.
        if y < -1e-9 or y > case.L + 1e-9:
            print(
                f"FAIL {case.name}: out of range, got {y!r} not in "
                f"[0, {case.L}] (L={case.L}, k={case.k}, x0={case.x0}, "
                f"x={case.x})",
                file=sys.stderr,
            )
            failed += 1
            continue

        print(f"PASS {case.name}: y={y:.6e}")

    if failed:
        print(f"\n{failed} case(s) failed", file=sys.stderr)
        return 1

    print(f"\nAll {len(list(_extreme_cases()))} cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
