"""Tests for the official-grade bridge (``swebench/official_grade.py``, C5 #319).

* **Hermetic** (CI): venv resolution + the subprocess wrapper with the official
  grading subprocess mocked.
* **``@integration``** (gated on an isolated ``swebench==4.1.0`` venv via
  ``ONLYCODES_SWEBENCH_VENV``): real grading of synthetic logs against a
  committed instance fixture — no network, no Docker, but needs the venv.
"""

from __future__ import annotations

import json
import os
import subprocess
import types
from pathlib import Path

import pytest

from swebench import official_grade as og

FIXTURE = Path(__file__).parent / "fixtures" / "swe_instance_psf__requests-1142.json"


def _instance() -> dict:
    return json.loads(FIXTURE.read_text())


def _coerce(v):
    return json.loads(v) if isinstance(v, str) else v


# --------------------------------------------------------------------------
# Hermetic
# --------------------------------------------------------------------------

def test_ensure_official_venv_uses_override_python(tmp_path, monkeypatch) -> None:
    venv = tmp_path / "v"
    (venv / "bin").mkdir(parents=True)
    py = venv / "bin" / "python"
    py.write_text("#!/bin/sh\n")
    monkeypatch.setenv("ONLYCODES_SWEBENCH_VENV", str(venv))
    assert og.ensure_official_venv() == str(py)
    # a direct python path is also accepted
    monkeypatch.setenv("ONLYCODES_SWEBENCH_VENV", str(py))
    assert og.ensure_official_venv() == str(py)


def test_ensure_official_venv_create_false_raises_when_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ONLYCODES_SWEBENCH_VENV", raising=False)
    monkeypatch.setattr(og, "_default_venv_dir", lambda: tmp_path / "nope")
    with pytest.raises(og.OfficialGradeError, match="not found"):
        og.ensure_official_venv(create=False)


def test_grade_parses_runner_json(monkeypatch) -> None:
    monkeypatch.setattr(og, "ensure_official_venv", lambda **kw: "/x/python")
    canned = {"resolution": "RESOLVED_FULL", "report": {}, "status_map": {"t": "PASSED"}}

    def _fake_run(argv, input=None, capture_output=None):
        assert argv[0] == "/x/python" and argv[1].endswith("_official_grade_runner.py")
        assert json.loads(input.decode())["instance"]["repo"]  # payload shape
        return types.SimpleNamespace(returncode=0, stdout=json.dumps(canned).encode(), stderr=b"")

    monkeypatch.setattr(og.subprocess, "run", _fake_run)
    out = og.grade(_instance(), "PASSED t\n")
    assert out == canned and og.is_resolved(out) is True


def test_grade_raises_on_runner_failure(monkeypatch) -> None:
    monkeypatch.setattr(og, "ensure_official_venv", lambda **kw: "/x/python")
    monkeypatch.setattr(og.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(
                            returncode=1, stdout=b"", stderr=b"boom"))
    with pytest.raises(og.OfficialGradeError, match="boom"):
        og.grade(_instance(), "log")


def test_is_resolved() -> None:
    assert og.is_resolved({"resolution": "RESOLVED_FULL"})
    assert not og.is_resolved({"resolution": "RESOLVED_PARTIAL"})
    assert not og.is_resolved({"resolution": "RESOLVED_NO"})
    assert not og.is_resolved({})


# --------------------------------------------------------------------------
# Integration: real official grading (needs the isolated venv)
# --------------------------------------------------------------------------

def _official_venv_available() -> bool:
    try:
        og.ensure_official_venv(create=False)
        return True
    except og.OfficialGradeError:
        return False


requires_official_venv = pytest.mark.skipif(
    not _official_venv_available(),
    reason="official swebench venv not available; set ONLYCODES_SWEBENCH_VENV",
)


@pytest.mark.integration
@requires_official_venv
def test_grade_real_full_resolution_and_no_resolution() -> None:
    inst = _instance()
    f2p, p2p = _coerce(inst["FAIL_TO_PASS"]), _coerce(inst["PASS_TO_PASS"])

    green = "\n".join(f"PASSED {t}" for t in f2p + p2p)
    g = og.grade(inst, green)
    assert g["resolution"] == "RESOLVED_FULL" and og.is_resolved(g)

    red = "\n".join([f"FAILED {t}" for t in f2p] + [f"PASSED {t}" for t in p2p])
    g2 = og.grade(inst, red)
    assert g2["resolution"] == "RESOLVED_NO" and not og.is_resolved(g2)
