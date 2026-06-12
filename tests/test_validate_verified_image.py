"""Orchestration tests for the verbatim gold-gate pool validator (Phase 4, #354).

Stubs Docker/HF entirely: we drive everything through a fake
``grading_official.grade_predictions`` and a fake ``_load_gold_patches`` and test
the *pool logic* — buildable / not_resolved / error / skipped classification,
resume carry-over of already-buildable instances, and the buildable-list +
results.json + summary.md outputs. No container internals here (the official
harness owns those).
"""

import argparse
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scripts.validate_verified_image as vvi  # noqa: E402


@pytest.fixture
def args(tmp_path):
    return argparse.Namespace(
        set="swe/swebench-verified", from_file=None, ids=None, limit=0,
        buildable_out=str(tmp_path / "buildable.txt"),
        out_dir=str(tmp_path / "out"),
        dataset_name="princeton-nlp/SWE-bench_Verified",
        run_id="test", parallel=2, fresh=False,
    )


def _patch(monkeypatch, *, gold, reports):
    """Stub HF gold sourcing and the verbatim batch grader.

    ``reports`` maps instance_id -> the per-instance report dict
    ``grade_predictions`` would return (e.g. ``{"resolved": True}``), or an
    Exception to raise from the whole call.
    """
    monkeypatch.setattr(vvi, "_load_gold_patches", lambda ids: dict(gold))

    def fake_grade(preds, *, run_id, model_name, max_workers, instance_ids, dataset_name):
        if isinstance(reports, Exception):
            raise reports
        return {iid: reports[iid] for iid in instance_ids}
    monkeypatch.setattr(vvi.grading_official, "grade_predictions", fake_grade)


def test_classifies_buildable_not_resolved_skipped(monkeypatch, args):
    args.ids = "psf__requests-1,psf__requests-2,psf__requests-3"
    _patch(monkeypatch,
           gold={"psf__requests-1": "P1", "psf__requests-2": "P2"},  # -3 has no gold
           reports={"psf__requests-1": {"resolved": True, "tests_status": {"x": 1}},
                    "psf__requests-2": {"resolved": False, "tests_status": {}}})

    assert vvi.run(args) == 0
    res = json.loads((Path(args.out_dir) / "results.json").read_text())
    status = {r["instance_id"]: r["status"] for r in res["rows"]}
    assert status == {"psf__requests-1": "buildable",
                      "psf__requests-2": "not_resolved",
                      "psf__requests-3": "skipped"}
    buildable = [l for l in Path(args.buildable_out).read_text().splitlines()
                 if l and not l.startswith("#")]
    assert buildable == ["psf__requests-1"]


def test_missing_report_is_error(monkeypatch, args):
    """A report carrying an ``error`` key (no report.json produced) -> error."""
    args.ids = "psf__requests-1"
    _patch(monkeypatch, gold={"psf__requests-1": "P1"},
           reports={"psf__requests-1": {"resolved": False, "error": "no report.json"}})
    assert vvi.run(args) == 0
    res = json.loads((Path(args.out_dir) / "results.json").read_text())
    assert res["rows"][0]["status"] == "error"
    assert "no report.json" in res["rows"][0]["reason"]


def test_grading_error_marks_chunk_error(monkeypatch, args):
    """A catastrophic GradingError (no per-instance reports) marks the whole chunk
    error and continues — the report is still the deliverable, run returns 0."""
    args.ids = "psf__requests-1,psf__requests-2"
    _patch(monkeypatch, gold={"psf__requests-1": "P1", "psf__requests-2": "P2"},
           reports=vvi.grading_official.GradingError("run_evaluation blew up"))
    assert vvi.run(args) == 0
    res = json.loads((Path(args.out_dir) / "results.json").read_text())
    status = {r["instance_id"]: r["status"] for r in res["rows"]}
    assert status == {"psf__requests-1": "error", "psf__requests-2": "error"}


def test_resume_carries_over_buildable_regrades_rest(monkeypatch, args):
    """Prior buildable verdicts are carried over (not re-graded); not_resolved /
    error / unreached instances are re-graded."""
    args.ids = "psf__requests-1,psf__requests-2,psf__requests-3"
    out = Path(args.out_dir); out.mkdir(parents=True)
    (out / "results.json").write_text(json.dumps({"rows": [
        {"instance_id": "psf__requests-1", "status": "buildable", "resolved": True},
        {"instance_id": "psf__requests-2", "status": "not_resolved", "resolved": False},
    ]}))
    graded_ids = {}

    def fake_grade(preds, *, run_id, model_name, max_workers, instance_ids, dataset_name):
        graded_ids["ids"] = list(instance_ids)
        return {iid: {"resolved": True} for iid in instance_ids}
    monkeypatch.setattr(vvi, "_load_gold_patches",
                        lambda ids: {i: "P" for i in ids})
    monkeypatch.setattr(vvi.grading_official, "grade_predictions", fake_grade)

    assert vvi.run(args) == 0
    # 1 carried over (not graded); 2 (not_resolved) and 3 (unreached) re-graded
    assert set(graded_ids["ids"]) == {"psf__requests-2", "psf__requests-3"}
    res = json.loads((out / "results.json").read_text())
    status = {r["instance_id"]: r["status"] for r in res["rows"]}
    assert status == {"psf__requests-1": "buildable", "psf__requests-2": "buildable",
                      "psf__requests-3": "buildable"}


def test_fresh_ignores_prior_results(monkeypatch, args):
    args.ids = "psf__requests-1"
    args.fresh = True
    out = Path(args.out_dir); out.mkdir(parents=True)
    (out / "results.json").write_text(json.dumps({"rows": [
        {"instance_id": "psf__requests-1", "status": "buildable", "resolved": True}]}))
    seen = {}

    def fake_grade(preds, *, run_id, model_name, max_workers, instance_ids, dataset_name):
        seen["ids"] = list(instance_ids)
        return {iid: {"resolved": False} for iid in instance_ids}
    monkeypatch.setattr(vvi, "_load_gold_patches", lambda ids: {i: "P" for i in ids})
    monkeypatch.setattr(vvi.grading_official, "grade_predictions", fake_grade)

    assert vvi.run(args) == 0
    assert seen["ids"] == ["psf__requests-1"]  # re-graded despite prior buildable
    res = json.loads((out / "results.json").read_text())
    assert res["rows"][0]["status"] == "not_resolved"


def test_limit_truncates(monkeypatch, args):
    args.ids = "a__b-1,a__b-2,a__b-3"
    args.limit = 2
    captured = {}

    def fake_grade(preds, *, run_id, model_name, max_workers, instance_ids, dataset_name):
        captured["ids"] = list(instance_ids)
        captured["workers"] = max_workers
        return {iid: {"resolved": True} for iid in instance_ids}
    monkeypatch.setattr(vvi, "_load_gold_patches", lambda ids: {i: "P" for i in ids})
    monkeypatch.setattr(vvi.grading_official, "grade_predictions", fake_grade)

    assert vvi.run(args) == 0
    assert captured["ids"] == ["a__b-1", "a__b-2"]
    assert captured["workers"] == 2  # --parallel mapped to max_workers


def test_summary_reports_shortfall(monkeypatch, args):
    args.ids = "psf__requests-1,psf__requests-2"
    _patch(monkeypatch, gold={"psf__requests-1": "P", "psf__requests-2": "P"},
           reports={"psf__requests-1": {"resolved": True},
                    "psf__requests-2": {"resolved": False}})
    assert vvi.run(args) == 0
    summary = (Path(args.out_dir) / "summary.md").read_text()
    assert "buildable (resolved=True): 1" in summary
    assert "shortfall (graded - buildable): 1" in summary


def test_row_from_report_classification():
    assert vvi._row_from_report("i", {"resolved": True})["status"] == "buildable"
    assert vvi._row_from_report("i", {"resolved": False})["status"] == "not_resolved"
    assert vvi._row_from_report("i", {"error": "x"})["status"] == "error"
