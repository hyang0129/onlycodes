"""Tests for the image-runtime orchestrator (``swebench/image_run.py``, C5 #319).

Hermetic: prompt/record/grading-instance assembly and the orchestration flow with
every container/agent/grade/image-store call mocked. The live end-to-end graded
arm is exercised via ``--runtime image`` (validated manually; too heavy/costly for
CI — it needs Docker, the official venv, and a paid agent turn).
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
    gi = image_run._grading_instance(_problem(), "TESTPATCH")
    assert gi["repo"] == "psf/requests" and gi["version"] == "1.1"
    assert gi["FAIL_TO_PASS"] == ["test_requests.py::T::test_no_content_length"]
    assert gi["PASS_TO_PASS"] == ["test_requests.py::T::test_basic_building"]
    assert gi["test_patch"] == "TESTPATCH" and gi["patch"] == ""  # gold not needed for agent arm


def test_extract_cost_turns(tmp_path) -> None:
    f = tmp_path / "t.jsonl"
    f.write_text('{"type":"assistant"}\n{"type":"result","total_cost_usd":0.05,"num_turns":7}\n')
    assert image_run._extract_cost_turns(str(f)) == (0.05, 7)


def test_write_record_meta_transcript_verdict(tmp_path) -> None:
    transcript = tmp_path / "tr.jsonl"
    transcript.write_text('{"type":"assistant"}\n{"type":"result","total_cost_usd":0.1}\n')
    image_run._write_record(
        str(tmp_path), _problem(), "onlycode", 0,
        transcript=str(transcript), verdict="PASS", resolution="RESOLVED_FULL",
        digest_info={"digest": "sha256:abc", "arch": "amd64"},
        cost=0.1, turns=3, agent_surface="claude_code", now=1.0,
    )
    rec = (tmp_path / "psf__requests-1142_onlycode_run0.jsonl").read_text().splitlines()
    meta = json.loads(rec[0])
    assert meta["type"] == "meta" and meta["runtime"] == "image"
    assert meta["verdict"] == "PASS" and meta["image_digest"] == "sha256:abc"
    assert meta["image_arch"] == "amd64" and meta["resolution"] == "RESOLVED_FULL"
    assert json.loads(rec[-1]) == {"type": "verdict", "verdict": "PASS", "resolution": "RESOLVED_FULL"}
    assert any('"type":"assistant"' in l or '"type": "assistant"' in l for l in rec)  # transcript inlined


def test_run_one_arm_pass_path(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(image_run.container, "start_arm_container",
                        lambda prepared, **kw: image_run.container.ContainerHandle("i", "cid", "snap"))
    monkeypatch.setattr(image_run.container_agent, "stage_arm", lambda h, **kw: None)
    def _fake_run_agent(h, **kw):
        Path(kw["result_path"]).write_text('{"type":"result","total_cost_usd":0.2,"num_turns":5}\n')
        return 0
    monkeypatch.setattr(image_run.container_agent, "run_agent", _fake_run_agent)
    monkeypatch.setattr(image_run.container_test, "grade_agent_run",
                        lambda h, gi, **kw: {"resolution": "RESOLVED_FULL"})
    monkeypatch.setattr(image_run.official_grade, "is_resolved", lambda g: True)
    teardown = []
    monkeypatch.setattr(image_run.container, "teardown", lambda h: teardown.append(h))

    verdict = image_run.run_one_arm(
        _problem(), arm="onlycode", run_idx=0,
        prepared=PreparedImage("psf__requests-1142", "base", "snap"),
        digest_info={"digest": "sha256:x", "arch": "amd64"},
        grading_instance={"repo": "psf/requests"}, spec_test_cmd="pytest -rA",
        eval_env={}, results_dir=str(tmp_path), _now=1.0,
    )
    assert verdict == "PASS"
    assert teardown, "container must be torn down"
    meta = json.loads((tmp_path / "psf__requests-1142_onlycode_run0.jsonl").read_text().splitlines()[0])
    assert meta["verdict"] == "PASS" and meta["total_cost_usd"] == 0.2


def test_run_image_arms_codex_surface_uses_codex_runtime(monkeypatch, tmp_path) -> None:
    calls = {}
    monkeypatch.setattr(image_run.image_store, "registry_login", lambda: False)
    monkeypatch.setattr(image_run.container_agent, "ensure_codex_runtime",
                        lambda **k: calls.setdefault("codex_rt", True) or "vol")
    monkeypatch.setattr(image_run.container_agent, "ensure_agent_runtime",
                        lambda *a, **k: calls.setdefault("claude_rt", True))
    monkeypatch.setattr(image_run, "run_one_arm",
                        lambda *a, **k: (calls.update(surface=k["agent_surface"],
                                                      model=k["codex_model"]), "PASS")[1])
    monkeypatch.setattr(image_run.image_store, "ensure_image",
                        lambda iid, **k: {"digest": "sha256:x", "arch": "amd64"})
    monkeypatch.setattr(image_run.container, "prepare_instance",
                        lambda iid, **k: PreparedImage(iid, "b", "s"))
    monkeypatch.setattr(image_run.specs, "spec_for", lambda r, v: {"test_cmd": "pytest -rA"})
    monkeypatch.setattr(image_run.specs, "eval_env", lambda s: {})

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


def test_run_image_arms_skips_without_grading_data(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(image_run.image_store, "registry_login", lambda: False)
    monkeypatch.setattr(image_run.container_agent, "ensure_agent_runtime", lambda b, **k: "vol")
    calls = []
    monkeypatch.setattr(image_run, "run_one_arm", lambda *a, **k: calls.append(k["arm"]) or "PASS")
    monkeypatch.setattr(image_run.image_store, "ensure_image",
                        lambda iid, **k: {"digest": "sha256:x", "arch": "amd64"})
    monkeypatch.setattr(image_run.container, "prepare_instance", lambda iid, **k: PreparedImage(iid, "b", "s"))
    monkeypatch.setattr(image_run.specs, "spec_for", lambda r, v: {"test_cmd": "pytest -rA"})
    monkeypatch.setattr(image_run.specs, "eval_env", lambda s: {})

    good = _problem(instance_id="psf__requests-1142")
    bad = _problem(instance_id="psf__requests-9999", fail_to_pass=None)
    out = image_run.run_image_arms([good, bad], arms=["onlycode"], num_runs=1,
                                   results_dir=str(tmp_path), agent_binary="claude", echo=lambda *a: None)
    assert out == [("psf__requests-1142", "onlycode", "PASS")]  # bad one skipped (no f2p)
