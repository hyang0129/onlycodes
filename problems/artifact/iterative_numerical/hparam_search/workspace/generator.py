#!/usr/bin/env python3
"""Workspace generator for iterative_numerical__hparam_search.

Writes a binary ``calibration.bin`` file holding the per-instance Gaussian
peak locations the ``toy_model`` uses. Peaks are derived deterministically
from the RNG seed the harness passes in (which is itself derived from
``sha256(instance_id)`` — see ``docs/SCHEMA_ARTIFACT.md`` §5.1).

The generator script itself is NEVER materialized into the agent's scratch
dir; only its output (``calibration.bin``) is visible to the agent. This is
the mechanism that makes the toy model's optimum unreachable from pure
source-code inspection — see issue #168.

Stdlib-only, per the materializer's scrubbed-env contract.
"""

from __future__ import annotations

import argparse
import math
import random
import struct
from pathlib import Path

# Calibration layout — KEEP IN SYNC with ``workspace/toy_model.py`` and
# ``grader/hidden.py``. Bumping ``_MAGIC`` is a breaking change: regenerate
# the reference_output if you ever do.
#
#   magic    (8 bytes ASCII)        — format/version tag
#   lr_peak  (double, little-endian)
#   hs_peak  (double, little-endian) — stored as float, cast to int by callers
#   do_peak  (double, little-endian)
#
# Total payload: 8 + 3*8 = 32 bytes.
_MAGIC = b"HPARMC01"
_STRUCT_FORMAT = "<3d"


def derive_peaks(seed: int) -> tuple[float, int, float]:
    """Return ``(lr_peak, hs_peak, do_peak)`` from a Python-RNG seed.

    Distributions are chosen so the optimum lands inside the search range
    declared by ``prompt.md`` but is *not* near the historical fixed
    ``(0.01, 128, 0.3)`` optimum that issue #168 retired.

    - ``lr_peak``: log-uniform in [3e-4, 5e-2]
    - ``hs_peak``: integer multiple of 8 in [32, 384]
    - ``do_peak``: uniform in [0.10, 0.60]
    """
    rng = random.Random(seed)
    lr_peak = 10 ** rng.uniform(math.log10(3e-4), math.log10(5e-2))
    hs_peak = 8 * rng.randint(4, 48)
    do_peak = rng.uniform(0.10, 0.60)
    return lr_peak, hs_peak, do_peak


def write_calibration(output_dir: Path, seed: int) -> None:
    lr_peak, hs_peak, do_peak = derive_peaks(seed)
    payload = struct.pack(_STRUCT_FORMAT, lr_peak, float(hs_peak), do_peak)
    out = output_dir / "calibration.bin"
    out.write_bytes(_MAGIC + payload)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--instance-id", type=str, required=False, default="")
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_calibration(args.output_dir, args.seed)


if __name__ == "__main__":
    main()
