"""Bridge to the official SWE-bench log parsers + grading (C5 #319).

The upstream ``swebench`` PyPI package ships ``MAP_REPO_TO_PARSER`` and the
``grading`` primitives, but its package name collides with ours, so it cannot be
imported in-process (same constraint as ``swebench/specs.py``). We run
``scripts/_official_grade_runner.py`` under an **isolated** ``swebench==<pin>``
venv and exchange JSON — exact grading parity, no in-process collision.

Reused by two callers — single-sourced so grading can't drift between them:

* C5 image-path grading (``FAIL_TO_PASS``->pass, ``PASS_TO_PASS`` stays green).
* The standalone gold-patch fidelity gate (#322) on the conda validator.

The venv is resolved via ``ONLYCODES_SWEBENCH_VENV`` (a venv dir or its python),
else built once under a cache dir.  ``swebench`` is **pinned** so a different
upstream release can't silently change parsing/grading.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

#: Pin must match ``scripts/extract_swebench_specs.py`` (the specs vendored from
#: the same release).  A different upstream may parse/grade differently.
PINNED_SWEBENCH = "swebench==4.1.0"

#: Full resolution = every FAIL_TO_PASS flipped and every PASS_TO_PASS held.
RESOLVED_FULL = "RESOLVED_FULL"

_RUNNER = Path(__file__).resolve().parent.parent / "scripts" / "_official_grade_runner.py"


class OfficialGradeError(RuntimeError):
    """The official grading subprocess could not run or returned bad output."""


def _default_venv_dir() -> Path:
    root = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(root) / "onlycodes" / "swe-official-venv"


def _venv_python(venv_dir: Path) -> Path:
    return venv_dir / "bin" / "python"


def ensure_official_venv(*, create: bool = True) -> str:
    """Return the python of an isolated venv with ``PINNED_SWEBENCH`` installed.

    Resolution order:

    1. ``ONLYCODES_SWEBENCH_VENV`` — a venv directory or a python path. Used
       as-is (never modified); raises if it doesn't look usable.
    2. A cached venv under ``~/.cache/onlycodes/swe-official-venv``; built on
       first use when ``create`` (pip-installs the pin — heavy, but once).

    Set ``create=False`` (e.g. in CI/hermetic contexts) to require a
    pre-provisioned venv and never pip-install.
    """
    override = os.environ.get("ONLYCODES_SWEBENCH_VENV")
    if override:
        p = Path(override)
        cand = p if p.name == "python" or p.suffix else _venv_python(p)
        if cand.is_file():
            return str(cand)
        raise OfficialGradeError(
            f"ONLYCODES_SWEBENCH_VENV={override!r} is not a usable venv/python"
        )

    venv_dir = _default_venv_dir()
    py = _venv_python(venv_dir)
    if py.is_file():
        return str(py)
    if not create:
        raise OfficialGradeError(
            f"official swebench venv not found at {venv_dir} and create=False; "
            "set ONLYCODES_SWEBENCH_VENV or pre-build it"
        )

    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True,
                   capture_output=True)
    subprocess.run([str(py), "-m", "pip", "install", "-q", PINNED_SWEBENCH],
                   check=True)
    return str(py)


def grade(instance: dict, log: str, *, create_venv: bool = True) -> dict:
    """Grade a test ``log`` for a SWE-bench ``instance`` via the official parsers.

    ``instance`` is a SWE-bench instance dict (needs at least ``repo``,
    ``version``, ``FAIL_TO_PASS``, ``PASS_TO_PASS``; ``make_test_spec`` also reads
    ``base_commit``/``patch``/``test_patch``/``problem_statement``/
    ``environment_setup_commit``/``instance_id``).

    Returns ``{"resolution", "report", "status_map"}``. Use :func:`is_resolved`
    for the boolean gate.
    """
    py = ensure_official_venv(create=create_venv)
    payload = json.dumps({"instance": instance, "log": log})
    proc = subprocess.run(
        [py, str(_RUNNER)],
        input=payload.encode(),
        capture_output=True,
    )
    if proc.returncode != 0:
        raise OfficialGradeError(
            f"official grade runner failed (exit {proc.returncode}): "
            f"{proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    try:
        return json.loads(proc.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError as e:
        raise OfficialGradeError(f"runner returned non-JSON: {e}") from e


def is_resolved(result: dict) -> bool:
    """True iff the grade is a full resolution (the SWE-bench 'solved' bar)."""
    return result.get("resolution") == RESOLVED_FULL
