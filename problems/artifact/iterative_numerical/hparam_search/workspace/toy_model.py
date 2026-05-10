"""Toy model for hparam_search benchmark.

``evaluate(learning_rate, hidden_size, dropout) -> accuracy``

The function's *shape* (three independent Gaussian factors) is fixed, but
its peak locations are loaded at import time from the per-instance
``calibration.bin`` data file shipped alongside this module. That file is
written by the task harness from a seed derived from the task's
``instance_id`` (see ``docs/SCHEMA_ARTIFACT.md`` §5.1) — so reading this
source file does NOT reveal the optimum. To find it, call ``evaluate``
and search.

The grader uses the same Gaussian formula, derives the same peaks
independently from the task's ``instance_id``, and re-evaluates the
reported hyperparameters. Hallucinated accuracy values are caught.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

_CALIBRATION_PATH = Path(__file__).parent / "calibration.bin"
_MAGIC = b"HPARMC01"
_STRUCT_FORMAT = "<3d"
_PAYLOAD_LEN = len(_MAGIC) + struct.calcsize(_STRUCT_FORMAT)


def _load_peaks() -> tuple[float, int, float]:
    if not _CALIBRATION_PATH.is_file():
        raise RuntimeError(
            f"missing {_CALIBRATION_PATH.name} — the workspace was not "
            "materialized by the task harness"
        )
    data = _CALIBRATION_PATH.read_bytes()
    if len(data) != _PAYLOAD_LEN or data[: len(_MAGIC)] != _MAGIC:
        raise RuntimeError(
            f"corrupt or unknown-format calibration file: {_CALIBRATION_PATH.name}"
        )
    lr_peak, hs_peak, do_peak = struct.unpack(_STRUCT_FORMAT, data[len(_MAGIC):])
    return lr_peak, int(round(hs_peak)), do_peak


_LR_PEAK, _HS_PEAK, _DO_PEAK = _load_peaks()


def evaluate(learning_rate: float, hidden_size: int, dropout: float) -> float:
    """Return the model accuracy for the given hyperparameters.

    Parameters
    ----------
    learning_rate : float
        Learning rate. Try values around 1e-4 – 0.1 (log scale recommended).
    hidden_size : int
        Number of hidden units. Try powers of 2: 16, 32, 64, 128, 256, 512.
    dropout : float
        Dropout rate in [0.0, 0.8].

    Returns
    -------
    float
        Accuracy in [0.0, 0.95]. Maximised when ``(learning_rate, hidden_size,
        dropout)`` matches the per-instance hidden peak — search to find it.
    """
    lr_score = math.exp(-3.0 * (math.log10(learning_rate / _LR_PEAK)) ** 2)
    hs_score = math.exp(-((hidden_size - _HS_PEAK) / 128.0) ** 2)
    do_score = math.exp(-((dropout - _DO_PEAK) / 0.2) ** 2)
    return round(0.95 * lr_score * hs_score * do_score, 6)
