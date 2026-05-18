"""Reference-output drift gate.

Asserts that every committed grader reference output matches what
``tools/regen_reference_outputs.py`` produces from the canonical
``_seed_for_instance(instance_id)`` seed. Catches the class of bug where a
reference was generated with the wrong seed (or with a stale generator)
and silently disagrees with the runtime materializer's output.

Runs the tool as a subprocess so the CLI contract (exit codes, stdout
diagnostics) is exercised the same way CI would invoke it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TOOL = _REPO_ROOT / "tools" / "regen_reference_outputs.py"


def test_no_reference_drift():
    """Every committed reference_output.* matches canonical regeneration."""
    proc = subprocess.run(
        [sys.executable, str(_TOOL), "--check"],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    if proc.returncode != 0:
        pytest.fail(
            "tools/regen_reference_outputs.py --check reported drift "
            "(or failed to run).\n"
            f"exit={proc.returncode}\n--- stdout ---\n{proc.stdout}"
            f"\n--- stderr ---\n{proc.stderr}\n"
            "Fix: regenerate the drifted reference(s) by running "
            "`python tools/regen_reference_outputs.py` and commit the result."
        )
