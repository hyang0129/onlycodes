"""Tests for :mod:`swebench.grading_official` — the verbatim grading adapter (#354).

Fast unit tests cover the report-parsing helper (``_collect_reports``) and the
``ensure_official_venv`` import-readiness / atomic-build logic without building a
real venv or touching docker. The ``@pytest.mark.integration`` test grades
``pytest-dev__pytest-5262`` with its gold patch through the real official
``run_evaluation`` and asserts ``resolved is True`` (docker + HF required).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swebench import grading_official as g


# --------------------------------------------------------------------------
# _collect_reports — pure report-tree parsing
# --------------------------------------------------------------------------

def _write_report(cwd: Path, run_id: str, model: str, iid: str, payload: dict) -> None:
    d = cwd / "logs" / "run_evaluation" / run_id / model / iid
    d.mkdir(parents=True, exist_ok=True)
    (d / "report.json").write_text(json.dumps({iid: payload}))


def test_collect_reports_resolved_unresolved_and_missing(tmp_path: Path) -> None:
    run_id, model = "run1", "onlycodes"
    _write_report(tmp_path, run_id, model, "repo__a-1", {
        "resolved": True,
        "patch_successfully_applied": True,
        "tests_status": {"FAIL_TO_PASS": {"success": ["t1"], "failure": []},
                         "PASS_TO_PASS": {"success": ["t2"], "failure": []}},
    })
    _write_report(tmp_path, run_id, model, "repo__b-2", {
        "resolved": False,
        "patch_successfully_applied": True,
        "tests_status": {"FAIL_TO_PASS": {"success": [], "failure": ["t1"]}},
    })

    ids = ["repo__a-1", "repo__b-2", "repo__c-3"]  # c-3 has no report
    out = g._collect_reports(tmp_path, run_id, model, ids)

    assert set(out) == set(ids)
    assert out["repo__a-1"]["resolved"] is True
    assert out["repo__a-1"]["patch_successfully_applied"] is True
    assert out["repo__a-1"]["tests_status"]["FAIL_TO_PASS"]["success"] == ["t1"]

    assert out["repo__b-2"]["resolved"] is False
    assert out["repo__b-2"]["patch_successfully_applied"] is True

    # missing report -> error record, never raised, resolved False
    assert out["repo__c-3"]["resolved"] is False
    assert "error" in out["repo__c-3"]


def test_collect_reports_unreadable_json(tmp_path: Path) -> None:
    run_id, model, iid = "run1", "onlycodes", "repo__a-1"
    d = tmp_path / "logs" / "run_evaluation" / run_id / model / iid
    d.mkdir(parents=True, exist_ok=True)
    (d / "report.json").write_text("{ not json")
    out = g._collect_reports(tmp_path, run_id, model, [iid])
    assert out[iid]["resolved"] is False
    assert "error" in out[iid]


def test_collect_reports_flat_shape(tmp_path: Path) -> None:
    """Tolerate a report not nested under the instance id."""
    run_id, model, iid = "run1", "onlycodes", "repo__a-1"
    d = tmp_path / "logs" / "run_evaluation" / run_id / model / iid
    d.mkdir(parents=True, exist_ok=True)
    (d / "report.json").write_text(json.dumps(
        {"resolved": True, "patch_successfully_applied": True, "tests_status": {}}))
    out = g._collect_reports(tmp_path, run_id, model, [iid])
    assert out[iid]["resolved"] is True


# --------------------------------------------------------------------------
# ensure_official_venv — readiness / atomic-build logic (no real venv)
# --------------------------------------------------------------------------

def test_ensure_venv_override_python(tmp_path: Path, monkeypatch) -> None:
    fake_py = tmp_path / "bin" / "python"
    fake_py.parent.mkdir(parents=True)
    fake_py.write_text("#!/bin/sh\n")
    monkeypatch.setenv("ONLYCODES_SWEBENCH_VENV", str(fake_py))
    assert g.ensure_official_venv() == str(fake_py)


def test_ensure_venv_override_missing_raises(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ONLYCODES_SWEBENCH_VENV", str(tmp_path / "nope"))
    with pytest.raises(g.GradingError):
        g.ensure_official_venv()


def test_ensure_venv_half_built_triggers_rebuild(tmp_path: Path, monkeypatch) -> None:
    """A half-built venv (bin/python present but ``import swebench`` fails) must be
    treated as not-ready and trigger a rebuild — the #353 TOCTOU fix."""
    monkeypatch.delenv("ONLYCODES_SWEBENCH_VENV", raising=False)
    venv_dir = tmp_path / "swe-official-venv"
    monkeypatch.setattr(g, "_default_venv_dir", lambda: venv_dir)

    # Simulate the half-built venv: bin/python exists but import fails.
    (venv_dir / "bin").mkdir(parents=True)
    (venv_dir / "bin" / "python").write_text("#!/bin/sh\n")

    built = {"called": False}

    def fake_build(target: Path) -> None:
        built["called"] = True
        # Pretend the rebuild produced a ready venv.
        monkeypatch.setattr(g, "_import_ready",
                            lambda py: Path(py) == g._venv_python(target))

    monkeypatch.setattr(g, "_build_venv_atomic", fake_build)
    # First check (on the half-built venv) must report not-ready.
    monkeypatch.setattr(g, "_import_ready", lambda py: False)

    result = g.ensure_official_venv()
    assert built["called"] is True
    assert result == str(g._venv_python(venv_dir))


def test_ensure_venv_create_false_when_not_ready(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ONLYCODES_SWEBENCH_VENV", raising=False)
    venv_dir = tmp_path / "swe-official-venv"
    monkeypatch.setattr(g, "_default_venv_dir", lambda: venv_dir)
    monkeypatch.setattr(g, "_import_ready", lambda py: False)
    with pytest.raises(g.GradingError):
        g.ensure_official_venv(create=False)


def test_ensure_venv_ready_returns_without_build(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ONLYCODES_SWEBENCH_VENV", raising=False)
    venv_dir = tmp_path / "swe-official-venv"
    monkeypatch.setattr(g, "_default_venv_dir", lambda: venv_dir)
    monkeypatch.setattr(g, "_import_ready", lambda py: True)

    def boom(target: Path) -> None:
        raise AssertionError("must not rebuild a ready venv")

    monkeypatch.setattr(g, "_build_venv_atomic", boom)
    assert g.ensure_official_venv() == str(g._venv_python(venv_dir))


def test_grade_predictions_empty_raises() -> None:
    with pytest.raises(g.GradingError):
        g.grade_predictions([], run_id="x")


def test_import_ready_missing_file(tmp_path: Path) -> None:
    assert g._import_ready(tmp_path / "absent") is False


# --------------------------------------------------------------------------
# Integration: real verbatim grade of a gold patch (docker + HF required)
# --------------------------------------------------------------------------

def _load_gold_patch(instance_id: str) -> str:
    """Stream the HF Verified split and return the gold ``patch`` for one id.

    Mirrors ``scripts/validate_verified_image.py:_load_gold_patches`` (single-id)."""
    from datasets import load_dataset

    for name, split in [("princeton-nlp/SWE-bench_Verified", "test"),
                        ("princeton-nlp/SWE-bench", "test")]:
        ds = load_dataset(name, split=split, streaming=True)
        for row in ds:
            if row.get("instance_id") == instance_id:
                return row.get("patch", "")
    raise AssertionError(f"gold patch not found on HF for {instance_id}")


@pytest.mark.integration
def test_grade_one_gold_resolved() -> None:
    iid = "pytest-dev__pytest-5262"
    gold = _load_gold_patch(iid)
    assert gold, "gold patch must be non-empty"
    report = g.grade_one(iid, gold)
    assert report["resolved"] is True
