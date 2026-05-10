"""Regression tests for ``problems/artifact/iterative_numerical/hparam_search``.

Background — issue #168 retired the original ``toy_model.py`` whose
peak constants ``(0.01, 128, 0.3)`` were visible in source. The replacement
derives Gaussian peaks per-instance from ``sha256(instance_id)`` and ships
them as a binary calibration file produced by ``workspace/generator.py``.

These tests pin three invariants:

1. The historical "read it from source" answer ``(0.01, 128, 0.3)`` no
   longer scores anywhere near the ``0.90`` accuracy target — agents that
   inspect the source instead of searching will fail the grader.
2. The generator and the grader derive the *same* peaks for the task's
   pinned ``instance_id`` (they must stay in lockstep — schema §3.1).
3. The harness-derived seed (``sha256(instance_id)[:8]`` as int) plumbed
   through ``workspace/generator.py`` produces a ``calibration.bin`` that,
   when loaded by ``workspace/toy_model.py``, agrees with the grader's
   in-source derivation.
"""

from __future__ import annotations

import hashlib
import importlib.util
import math
import struct
import sys
import tempfile
from pathlib import Path

import pytest


_TASK_DIR = (
    Path(__file__).resolve().parent.parent
    / "problems"
    / "artifact"
    / "iterative_numerical"
    / "hparam_search"
)
_INSTANCE_ID = "iterative_numerical__hparam_search"


def _load_module(name: str, path: Path):
    """Load a module from an explicit path without polluting sys.modules permanently."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def _seed_for_instance(instance_id: str) -> int:
    """Mirror of ``swebench.artifact_materialize._seed_for_instance``."""
    digest = hashlib.sha256(instance_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


@pytest.fixture(scope="module")
def grader_module():
    return _load_module(
        "hparam_search_hidden",
        _TASK_DIR / "grader" / "hidden.py",
    )


@pytest.fixture(scope="module")
def generator_module():
    return _load_module(
        "hparam_search_generator",
        _TASK_DIR / "workspace" / "generator.py",
    )


def test_old_inspect_answer_no_longer_wins(grader_module) -> None:
    """The historical literal answer ``(0.01, 128, 0.3)`` MUST fail the grader.

    Pre-issue #168, the Gaussian peaks lived as constants in
    ``toy_model.py``; an agent could read them and report ``(0.01, 128, 0.3)``
    without searching. After the fix the peaks are per-instance, so the old
    inspection answer should not even come close to the accuracy target.
    """
    acc = grader_module._evaluate(0.01, 128, 0.3)
    assert acc < grader_module.ACCURACY_TARGET, (
        f"old (0.01, 128, 0.3) still scores {acc} ≥ target "
        f"{grader_module.ACCURACY_TARGET} — search is not being exercised"
    )
    # Stronger: it should not even be in the same league as the target.
    assert acc < 0.5 * grader_module.ACCURACY_TARGET, (
        f"old (0.01, 128, 0.3) scores {acc}, suspiciously close to target — "
        "did the per-instance peaks land near the historical optimum?"
    )


def test_global_optimum_not_near_historical(grader_module) -> None:
    """At least one derived peak must be meaningfully off ``(0.01, 128, 0.3)``."""
    lr_peak = grader_module._LR_PEAK
    hs_peak = grader_module._HS_PEAK
    do_peak = grader_module._DO_PEAK

    lr_off = abs(math.log10(lr_peak / 0.01))   # log-space distance
    hs_off = abs(hs_peak - 128)
    do_off = abs(do_peak - 0.3)

    # At least one axis must be clearly off the historical peak. Thresholds are
    # generous (1 decade in LR, 32 units in HS, 0.1 in dropout) so a benign
    # future change to the derivation cannot silently re-converge.
    assert (lr_off >= 0.3) or (hs_off >= 32) or (do_off >= 0.1), (
        f"derived peaks {lr_peak, hs_peak, do_peak} are dangerously close to "
        "the historical (0.01, 128, 0.3) — agents could still inspect-solve"
    )


def test_grader_optimum_scores_above_target(grader_module) -> None:
    """The grader's own derived peaks must achieve the accuracy target.

    This is a smoke check: if the peak derivation drifts so far that no point
    in the declared search space hits 0.90, the task becomes unsolvable.
    """
    acc = grader_module._evaluate(
        grader_module._LR_PEAK,
        grader_module._HS_PEAK,
        grader_module._DO_PEAK,
    )
    assert acc >= grader_module.ACCURACY_TARGET
    # The unrounded max is 0.95 by construction; allow small rounding slop.
    assert acc >= 0.94


def test_generator_and_grader_derive_same_peaks(grader_module, generator_module) -> None:
    """Generator (writes calibration.bin) and grader (re-derives in source) must agree."""
    seed = _seed_for_instance(_INSTANCE_ID)
    gen_lr, gen_hs, gen_do = generator_module.derive_peaks(seed)
    assert gen_lr == pytest.approx(grader_module._LR_PEAK, rel=0, abs=0)
    assert gen_hs == grader_module._HS_PEAK
    assert gen_do == pytest.approx(grader_module._DO_PEAK, rel=0, abs=0)


def test_calibration_roundtrip_via_generator(generator_module) -> None:
    """End-to-end: run the generator and reload the same peaks through toy_model.

    Reproduces what the harness does:

    1. ``swebench.artifact_materialize`` derives seed from instance_id.
    2. Generator is invoked as a subprocess, writes ``calibration.bin``.
    3. Agent imports ``toy_model``, which reads the binary file.

    We verify that the round-trip preserves the peak values exactly.
    """
    seed = _seed_for_instance(_INSTANCE_ID)
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        # Copy toy_model.py next to the calibration file the generator will
        # write — toy_model reads ``Path(__file__).parent / "calibration.bin"``.
        toy_model_src = (_TASK_DIR / "workspace" / "toy_model.py").read_text()
        (scratch / "toy_model.py").write_text(toy_model_src)
        generator_module.write_calibration(scratch, seed)

        # Sanity-check the calibration file shape.
        data = (scratch / "calibration.bin").read_bytes()
        assert data[:8] == b"HPARMC01"
        assert len(data) == 8 + struct.calcsize("<3d")

        # Load toy_model from the tmp dir so it picks up the local
        # ``calibration.bin`` rather than the committed one (if any).
        module = _load_module("hparam_search_toy_model_tmp", scratch / "toy_model.py")
        lr_peak, hs_peak, do_peak = generator_module.derive_peaks(seed)
        assert module._LR_PEAK == lr_peak
        assert module._HS_PEAK == hs_peak
        assert module._DO_PEAK == do_peak


def test_calibration_bin_is_not_committed_to_workspace() -> None:
    """``calibration.bin`` must be generated at materialize time, not committed.

    Committing it would defeat the no-leak invariant: the binary would be
    visible in the agent's scratch dir *with* a stable shape regardless of
    instance_id, and (more importantly) it would be readable directly from
    the source tree without the per-instance derivation ever running.
    """
    calibration_path = _TASK_DIR / "workspace" / "calibration.bin"
    assert not calibration_path.exists(), (
        f"{calibration_path} should not be committed — "
        "the workspace generator produces it at materialize time"
    )
