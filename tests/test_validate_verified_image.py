"""Orchestration tests for the image-runtime gold-gate pool validator (#308).

Stubs Docker/HF entirely: we test the *pool logic* — pre-flight skips,
buildable/not_resolved/error classification, continue-on-error, and the
buildable-list + summary outputs — not the container internals (those are covered
by test_container_test.py / test_image_run.py).
"""

import argparse
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scripts.validate_verified_image as vvi  # noqa: E402


def _problem(iid, *, repo="psf/requests", version="2.0", f2p=("t::a",)):
    from swebench.models import Problem
    return Problem(
        instance_id=iid, repo_slug=repo, base_commit="abc", test_cmd="pytest",
        problem_statement="x", patch_file=None, added_at="2026", hf_split="test",
        version=version, environment_setup_commit="abc",
        fail_to_pass=list(f2p) if f2p else None, pass_to_pass=[],
    )


@pytest.fixture
def args(tmp_path):
    return argparse.Namespace(
        set="swe/swebench-verified", from_file=None, ids=None, limit=0,
        buildable_out=str(tmp_path / "buildable.txt"),
        out_dir=str(tmp_path / "out"), cap_gb=None, timeout=60,
    )


def _patch_common(monkeypatch, *, gold, grades):
    """Stub HF gold sourcing, registry login, repo grouping, specs, and the gate.

    ``grades`` maps instance_id -> a grade dict (or an Exception to raise).
    """
    monkeypatch.setattr(vvi.image_store, "registry_login", lambda: True)
    monkeypatch.setattr(vvi, "_await_pull_budget", lambda **kw: None)  # no network probe in tests
    monkeypatch.setattr(vvi.image_store, "group_by_repo_version", lambda ids: list(ids))
    monkeypatch.setattr(vvi, "_load_gold_patches", lambda ids: dict(gold))
    monkeypatch.setattr(vvi.specs, "spec_for",
                        lambda repo, ver: {"test_cmd": "pytest -q"})
    monkeypatch.setattr(vvi.specs, "eval_env", lambda spec: {})
    monkeypatch.setattr(vvi.image_store, "ensure_image",
                        lambda iid, cap_gb=None: {"digest": f"sha256:{iid}", "pruned": []})
    monkeypatch.setattr(vvi.container, "prepare_instance", lambda iid: object())
    monkeypatch.setattr(vvi.container, "start_arm_container", lambda prepared: object())
    monkeypatch.setattr(vvi.container, "teardown", lambda h: None)

    def fake_gate(handle, instance, **kw):
        g = grades[instance["instance_id"]]
        if isinstance(g, Exception):
            raise g
        return g
    monkeypatch.setattr(vvi.container_test, "gold_patch_gate", fake_gate)


def test_classifies_buildable_drift_and_error(monkeypatch, args, tmp_path):
    problems = [_problem("psf__requests-1"), _problem("psf__requests-2"),
                _problem("psf__requests-3")]
    monkeypatch.setattr(vvi, "_load_problems", lambda ids, d: (problems, []))
    args.ids = "psf__requests-1,psf__requests-2,psf__requests-3"
    _patch_common(monkeypatch, gold={p.instance_id: "PATCH" for p in problems}, grades={
        "psf__requests-1": {"resolution": "RESOLVED_FULL"},
        "psf__requests-2": {"resolution": "RESOLVED_PARTIAL", "FAIL_TO_PASS": {}},
        "psf__requests-3": RuntimeError("pull blew up"),
    })

    assert vvi.run(args) == 0
    res = json.loads((Path(args.out_dir) / "results.json").read_text())
    status = {r["instance_id"]: r["status"] for r in res["rows"]}
    assert status == {"psf__requests-1": "buildable",
                      "psf__requests-2": "not_resolved",
                      "psf__requests-3": "error"}
    # buildable list holds only the RESOLVED_FULL id
    buildable = [l for l in Path(args.buildable_out).read_text().splitlines()
                 if l and not l.startswith("#")]
    assert buildable == ["psf__requests-1"]


def test_preflight_skips_recorded_not_gated(monkeypatch, args):
    p_ok = _problem("psf__requests-1")
    p_nof2p = _problem("psf__requests-2", f2p=None)        # no fail_to_pass
    p_nogold = _problem("psf__requests-3")                  # gold missing on HF
    monkeypatch.setattr(vvi, "_load_problems",
                        lambda ids, d: ([p_ok, p_nof2p, p_nogold], []))
    args.ids = "psf__requests-1,psf__requests-2,psf__requests-3"
    # gold present for 1 only; 3 absent -> skipped, never reaches the gate
    _patch_common(monkeypatch, gold={"psf__requests-1": "PATCH"},
                  grades={"psf__requests-1": {"resolution": "RESOLVED_FULL"}})

    assert vvi.run(args) == 0
    res = json.loads((Path(args.out_dir) / "results.json").read_text())
    status = {r["instance_id"]: r["status"] for r in res["rows"]}
    assert status["psf__requests-1"] == "buildable"
    assert status["psf__requests-2"] == "skipped"
    assert status["psf__requests-3"] == "skipped"
    reasons = {r["instance_id"]: r.get("reason") for r in res["rows"]}
    assert "fail_to_pass" in reasons["psf__requests-2"]
    assert "gold patch" in reasons["psf__requests-3"]


def test_await_pull_budget_sleeps_until_refill():
    """Blocks while remaining < min, returns once it refills; no-op when probe is None."""
    budgets = iter([(0, 200), (3, 200), (50, 200)])
    slept = []
    vvi._await_pull_budget(min_remaining=8, poll_s=300,
                           _sleep=lambda s: slept.append(s),
                           _probe=lambda: next(budgets))
    assert slept == [300, 300]  # waited through 0/200 and 3/200, proceeded at 50/200

    # undeterminable budget (unlimited account / mirror / offline) -> immediate return
    vvi._await_pull_budget(_sleep=lambda s: (_ for _ in ()).throw(AssertionError("slept")),
                           _probe=lambda: None)


def test_rate_limit_pull_is_retried_not_marked_error(monkeypatch, args):
    """A rate-limit ContainerError on pull must NOT mark the instance error — it
    waits and retries the same instance until the pull succeeds."""
    from swebench.container import ContainerError
    p = _problem("psf__requests-1")
    monkeypatch.setattr(vvi, "_load_problems", lambda ids, d: ([p], []))
    args.ids = "psf__requests-1"
    _patch_common(monkeypatch, gold={"psf__requests-1": "P"},
                  grades={"psf__requests-1": {"resolution": "RESOLVED_FULL"}})
    monkeypatch.setattr(vvi.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def flaky_ensure(iid, cap_gb=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ContainerError("pull foo failed: toomanyrequests: rate limited")
        return {"digest": "sha256:x", "pruned": []}
    monkeypatch.setattr(vvi.image_store, "ensure_image", flaky_ensure)

    assert vvi.run(args) == 0
    res = json.loads((Path(args.out_dir) / "results.json").read_text())
    assert res["rows"][0]["status"] == "buildable"
    assert calls["n"] == 2  # first call rate-limited, retried, second succeeded


def test_is_rate_limit_error():
    from swebench.container import ContainerError
    assert vvi._is_rate_limit_error(ContainerError("... toomanyrequests ..."))
    assert vvi._is_rate_limit_error(Exception("pull exhausted retries (rate limited)"))
    assert not vvi._is_rate_limit_error(Exception("no such image"))


def test_summary_reports_shortfall(monkeypatch, args):
    problems = [_problem("psf__requests-1"), _problem("psf__requests-2")]
    monkeypatch.setattr(vvi, "_load_problems", lambda ids, d: (problems, []))
    args.ids = "psf__requests-1,psf__requests-2"
    _patch_common(monkeypatch, gold={p.instance_id: "P" for p in problems}, grades={
        "psf__requests-1": {"resolution": "RESOLVED_FULL"},
        "psf__requests-2": {"resolution": "RESOLVED_NO"},
    })
    assert vvi.run(args) == 0
    summary = (Path(args.out_dir) / "summary.md").read_text()
    assert "buildable (RESOLVED_FULL): 1" in summary
    assert "shortfall (gated - buildable): 1" in summary
