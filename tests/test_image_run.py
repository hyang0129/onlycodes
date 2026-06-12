"""Tests for the image-runtime orchestrator (``swebench/image_run.py``, #319/#354).

Hermetic: the two decoupled passes — agent (Concern A) and verbatim grading
(Concern B) — are exercised with every container/agent/image-store call mocked,
``container_agent.run_agent``/``extract_agent_diff`` stubbed to emit a fake
transcript + known patch, and ``grading_official.grade_predictions`` stubbed to
return chosen reports. The live end-to-end graded arm is exercised via
``--runtime image`` (validated manually; too heavy/costly for CI — it needs
Docker, the official venv, and a paid agent turn).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swebench import image_run
from swebench.container import PreparedImage
from swebench.models import Problem


def _problem(**kw) -> Problem:
    base = dict(
        instance_id="psf__requests-1142", repo_slug="psf/requests", base_commit="abc",
        test_cmd="pytest", problem_statement="GET sends Content-Length", patch_file=None,
        added_at="", hf_split="test", version="1.1",
        fail_to_pass=["test_requests.py::T::test_no_content_length"],
        pass_to_pass=["test_requests.py::T::test_basic_building"],
    )
    base.update(kw)
    return Problem(**base)


def test_build_prompt_onlycode_vs_baseline() -> None:
    p = _problem()
    only = image_run._build_prompt(p, "onlycode")
    base = image_run._build_prompt(p, "baseline")
    assert "/testbed" in only and "/opt/miniconda3/envs/testbed/bin/python" in only
    assert "codebox" in only and "codebox" not in base  # restriction guidance only for code arm
    assert p.problem_statement in only and p.problem_statement in base


def test_grading_instance_from_problem_has_f2p_p2p_no_gold() -> None:
    # Retained for the validation scripts (Phase 4); not used by the image runtime.
    gi = image_run._grading_instance(_problem(), "TESTPATCH")
    assert gi["repo"] == "psf/requests" and gi["version"] == "1.1"
    assert gi["FAIL_TO_PASS"] == ["test_requests.py::T::test_no_content_length"]
    assert gi["PASS_TO_PASS"] == ["test_requests.py::T::test_basic_building"]
    assert gi["test_patch"] == "TESTPATCH" and gi["patch"] == ""  # gold not needed for agent arm


def test_extract_cost_turns(tmp_path) -> None:
    f = tmp_path / "t.jsonl"
    f.write_text('{"type":"assistant"}\n{"type":"result","total_cost_usd":0.05,"num_turns":7}\n')
    assert image_run._extract_cost_turns(str(f)) == (0.05, 7)


def test_write_record_pending_carries_model_patch(tmp_path) -> None:
    transcript = tmp_path / "tr.jsonl"
    transcript.write_text('{"type":"assistant"}\n{"type":"result","total_cost_usd":0.1}\n')
    path = image_run._write_record(
        str(tmp_path), _problem(), "onlycode", 0,
        transcript=str(transcript), verdict="PENDING", resolution=None,
        model_patch="diff --git a/x b/x\n",
        digest_info={"digest": "sha256:abc", "arch": "amd64"},
        cost=0.1, turns=3, agent_surface="claude_code", now=1.0,
    )
    rec = Path(path).read_text().splitlines()
    meta = json.loads(rec[0])
    assert meta["type"] == "meta" and meta["runtime"] == "image"
    assert meta["verdict"] == "PENDING" and meta["resolution"] is None
    assert meta["model_patch"] == "diff --git a/x b/x\n"
    assert meta["image_digest"] == "sha256:abc" and meta["image_arch"] == "amd64"
    assert json.loads(rec[-1]) == {"type": "verdict", "verdict": "PENDING", "resolution": None}
    assert any('"type":"assistant"' in l or '"type": "assistant"' in l for l in rec)  # transcript inlined


def test_finalize_record_merges_verdict_preserving_transcript(tmp_path) -> None:
    transcript = tmp_path / "tr.jsonl"
    transcript.write_text('{"type":"assistant"}\n{"type":"result"}\n')
    path = image_run._write_record(
        str(tmp_path), _problem(), "onlycode", 0,
        transcript=str(transcript), verdict="PENDING", resolution=None,
        model_patch="PATCH", digest_info={"digest": "d", "arch": "amd64"},
        cost=None, turns=None, agent_surface="claude_code", now=1.0,
    )
    image_run._finalize_record(path, "PASS", "RESOLVED_FULL")
    rec = Path(path).read_text().splitlines()
    meta = json.loads(rec[0])
    assert meta["verdict"] == "PASS" and meta["resolution"] == "RESOLVED_FULL"
    assert meta["model_patch"] == "PATCH"  # preserved
    assert json.loads(rec[-1]) == {"type": "verdict", "verdict": "PASS", "resolution": "RESOLVED_FULL"}
    # Transcript lines survive between meta and verdict; exactly one verdict line.
    assert sum(1 for l in rec if l.strip() and json.loads(l).get("type") == "verdict") == 1
    assert any(json.loads(l).get("type") == "assistant" for l in rec)


def test_run_one_arm_captures_patch_and_writes_pending(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(image_run.container, "start_arm_container",
                        lambda prepared, **kw: image_run.container.ContainerHandle("i", "cid", "snap"))
    monkeypatch.setattr(image_run.container_agent, "stage_arm", lambda h, **kw: None)

    def _fake_run_agent(h, **kw):
        Path(kw["result_path"]).write_text('{"type":"result","total_cost_usd":0.2,"num_turns":5}\n')
        return 0

    monkeypatch.setattr(image_run.container_agent, "run_agent", _fake_run_agent)
    monkeypatch.setattr(image_run.container_agent, "extract_agent_diff",
                        lambda h, dest: "diff --git a/f b/f\n")
    teardown = []
    monkeypatch.setattr(image_run.container, "teardown", lambda h: teardown.append(h))

    pred = image_run.run_one_arm(
        _problem(), arm="onlycode", run_idx=0,
        prepared=PreparedImage("psf__requests-1142", "base", "snap"),
        digest_info={"digest": "sha256:x", "arch": "amd64"},
        results_dir=str(tmp_path), _now=1.0,
    )
    assert pred["instance_id"] == "psf__requests-1142" and pred["arm"] == "onlycode"
    assert pred["model_patch"] == "diff --git a/f b/f\n"
    assert teardown, "container must be torn down"
    meta = json.loads(Path(pred["record_path"]).read_text().splitlines()[0])
    assert meta["verdict"] == "PENDING" and meta["total_cost_usd"] == 0.2
    assert meta["model_patch"] == "diff --git a/f b/f\n"


def _stub_agent_pass(monkeypatch, *, patch="diff --git a/f b/f\n"):
    """Stub the whole agent pass so only the two-pass orchestration is exercised."""
    monkeypatch.setattr(image_run.image_store, "registry_login", lambda: False)
    monkeypatch.setattr(image_run.container_agent, "ensure_agent_runtime", lambda b, **k: "vol")
    monkeypatch.setattr(image_run.container_agent, "ensure_codex_runtime", lambda **k: "vol")
    monkeypatch.setattr(image_run.image_store, "group_by_repo_version", lambda ids: list(ids))
    monkeypatch.setattr(image_run.image_store, "ensure_image",
                        lambda iid, **k: {"digest": "sha256:x", "arch": "amd64"})
    monkeypatch.setattr(image_run.container, "prepare_instance",
                        lambda iid, **k: PreparedImage(iid, "b", "s"))
    monkeypatch.setattr(image_run.container, "start_arm_container",
                        lambda prepared, **kw: image_run.container.ContainerHandle("i", "cid", "snap"))
    monkeypatch.setattr(image_run.container_agent, "stage_arm", lambda h, **kw: None)
    monkeypatch.setattr(image_run.container, "teardown", lambda h: None)

    def _fake_run_agent(h, **kw):
        Path(kw["result_path"]).write_text('{"type":"result","total_cost_usd":0.1,"num_turns":2}\n')
        return 0

    monkeypatch.setattr(image_run.container_agent, "run_agent", _fake_run_agent)
    monkeypatch.setattr(image_run.container_agent, "extract_agent_diff",
                        lambda h, dest: patch)


def test_run_image_arms_two_pass_pass(monkeypatch, tmp_path) -> None:
    _stub_agent_pass(monkeypatch)
    seen = {}

    def _fake_grade(preds, **kw):
        seen["preds"] = preds
        seen["model_name"] = kw["model_name"]
        seen["run_id"] = kw["run_id"]
        seen["max_workers"] = kw["max_workers"]
        return {p["instance_id"]: {"resolved": True} for p in preds}

    monkeypatch.setattr(image_run.grading_official, "grade_predictions", _fake_grade)

    out = image_run.run_image_arms(
        [_problem()], arms=["onlycode"], num_runs=1,
        results_dir=str(tmp_path), agent_binary="claude",
        grading_max_workers=3, echo=lambda *a: None,
    )
    assert out == [("psf__requests-1142", "onlycode", "PASS")]
    # Predictions assembled from the captured patches.
    assert seen["preds"] == [{"instance_id": "psf__requests-1142", "model_patch": "diff --git a/f b/f\n"}]
    assert seen["model_name"] == "onlycode" and seen["max_workers"] == 3
    assert str(image_run.os.getpid()) in seen["run_id"]
    # Record finalized with the merged verdict.
    meta = json.loads((tmp_path / "psf__requests-1142_onlycode_run0.jsonl").read_text().splitlines()[0])
    assert meta["verdict"] == "PASS" and meta["resolution"] == "RESOLVED_FULL"
    assert meta["model_patch"] == "diff --git a/f b/f\n"


def test_run_image_arms_two_pass_fail(monkeypatch, tmp_path) -> None:
    _stub_agent_pass(monkeypatch)
    monkeypatch.setattr(image_run.grading_official, "grade_predictions",
                        lambda preds, **kw: {p["instance_id"]: {"resolved": False} for p in preds})

    out = image_run.run_image_arms(
        [_problem()], arms=["onlycode"], num_runs=1,
        results_dir=str(tmp_path), agent_binary="claude", echo=lambda *a: None,
    )
    assert out == [("psf__requests-1142", "onlycode", "FAIL")]
    meta = json.loads((tmp_path / "psf__requests-1142_onlycode_run0.jsonl").read_text().splitlines()[0])
    assert meta["verdict"] == "FAIL" and meta["resolution"] is None


def test_run_image_arms_two_pass_error_empty_patch(monkeypatch, tmp_path) -> None:
    # Agent made no change -> empty patch; grader returns an error report -> ERROR.
    _stub_agent_pass(monkeypatch, patch="")
    captured = {}

    def _fake_grade(preds, **kw):
        captured["preds"] = preds
        return {p["instance_id"]: {"resolved": False, "error": "patch did not apply"} for p in preds}

    monkeypatch.setattr(image_run.grading_official, "grade_predictions", _fake_grade)

    out = image_run.run_image_arms(
        [_problem()], arms=["onlycode"], num_runs=1,
        results_dir=str(tmp_path), agent_binary="claude", echo=lambda *a: None,
    )
    assert out == [("psf__requests-1142", "onlycode", "ERROR")]
    assert captured["preds"][0]["model_patch"] == ""  # empty patch flowed through
    meta = json.loads((tmp_path / "psf__requests-1142_onlycode_run0.jsonl").read_text().splitlines()[0])
    assert meta["verdict"] == "ERROR" and meta["resolution"] == "patch did not apply"


def test_run_image_arms_codex_surface_uses_codex_runtime(monkeypatch, tmp_path) -> None:
    _stub_agent_pass(monkeypatch)
    calls = {}
    # Re-stub the runtime setup to record which surface was provisioned.
    monkeypatch.setattr(image_run.container_agent, "ensure_codex_runtime",
                        lambda **k: calls.setdefault("codex_rt", True) or "vol")
    monkeypatch.setattr(image_run.container_agent, "ensure_agent_runtime",
                        lambda *a, **k: calls.setdefault("claude_rt", True))

    def _record_surface(*a, **k):
        calls.update(surface=k["agent_surface"], model=k["codex_model"])
        return {"instance_id": a[0].instance_id, "arm": k["arm"], "run_idx": k["run_idx"],
                "model_patch": "P", "record_path": str(tmp_path / "r.jsonl")}

    monkeypatch.setattr(image_run, "run_one_arm", _record_surface)
    monkeypatch.setattr(image_run, "_finalize_record", lambda *a, **k: None)
    monkeypatch.setattr(image_run.grading_official, "grade_predictions",
                        lambda preds, **kw: {p["instance_id"]: {"resolved": True} for p in preds})

    out = image_run.run_image_arms([_problem()], arms=["onlycode"], num_runs=1,
                                   results_dir=str(tmp_path), agent_binary="codex",
                                   agent_surface="codex_cli", codex_model="gpt-5.4",
                                   echo=lambda *a: None)
    assert out == [("psf__requests-1142", "onlycode", "PASS")]
    assert calls.get("codex_rt") and "claude_rt" not in calls   # codex runtime, not claude
    assert calls["surface"] == "codex_cli" and calls["model"] == "gpt-5.4"


def test_extract_cost_turns_codex_counts_turns(tmp_path) -> None:
    f = tmp_path / "t.jsonl"
    f.write_text('{"type":"turn.started"}\n'
                 '{"type":"turn.completed","usage":{"input_tokens":10,"cached_input_tokens":0,"output_tokens":5}}\n')
    _cost, turns = image_run._extract_cost_turns(str(f), agent_surface="codex_cli", codex_model="gpt-5.5")
    assert turns == 1


def test_run_image_arms_skips_unpromptable(monkeypatch, tmp_path) -> None:
    # No longer skips on missing fail_to_pass (dataset supplies it); only skips
    # instances we genuinely cannot prompt (no problem_statement).
    _stub_agent_pass(monkeypatch)
    monkeypatch.setattr(image_run.grading_official, "grade_predictions",
                        lambda preds, **kw: {p["instance_id"]: {"resolved": True} for p in preds})

    good = _problem(instance_id="psf__requests-1142")
    no_f2p = _problem(instance_id="psf__requests-2222", fail_to_pass=None)  # graded anyway now
    unpromptable = _problem(instance_id="psf__requests-9999", problem_statement="")
    out = image_run.run_image_arms([good, no_f2p, unpromptable], arms=["onlycode"], num_runs=1,
                                   results_dir=str(tmp_path), agent_binary="claude", echo=lambda *a: None)
    iids = {iid for iid, _, _ in out}
    assert iids == {"psf__requests-1142", "psf__requests-2222"}  # no-f2p kept; unpromptable dropped
