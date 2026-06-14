"""Unit tests for the run-health audit (#305, WS-G).

Hermetic: every transcript is synthesised in ``tmp_path``. No network, no real
run dirs, no patterns.json touch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swebench.run_audit import (
    API_ERROR,
    EMPTY,
    MAX_TURNS,
    MCP_FAILED,
    NO_RESULT,
    OK,
    RATE_LIMITED,
    WALL_TIMEOUT,
    audit_dir,
    classify_run,
)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _write(path: Path, lines: list[dict | str]) -> Path:
    with path.open("w") as f:
        for ln in lines:
            f.write((ln if isinstance(ln, str) else json.dumps(ln)) + "\n")
    return path


def _claude_meta(arm: str = "baseline") -> dict:
    return {"type": "meta", "instance_id": "x__x-1", "arm": arm, "run": 0,
            "agent_surface": "claude_code", "runtime": "image"}


def _claude_result(**over) -> dict:
    base = {"type": "result", "subtype": "success", "is_error": False,
            "api_error_status": None, "stop_reason": "end_turn",
            "num_turns": 5, "total_cost_usd": 0.1}
    base.update(over)
    return base


def _rate_event(status: str = "allowed", overage: str = "allowed") -> dict:
    return {"type": "rate_limit_event",
            "rate_limit_info": {"status": status, "overageStatus": overage}}


def _claude_jsonl(tmp: Path, name: str, lines: list[dict | str]) -> Path:
    return _write(tmp / name, lines)


# ---------------------------------------------------------------------------
# Claude classification
# ---------------------------------------------------------------------------


def test_claude_healthy_is_ok(tmp_path):
    p = _claude_jsonl(tmp_path, "x__x-1_baseline_run0.jsonl",
                      [_claude_meta(), _rate_event("allowed"), _claude_result(),
                       {"type": "verdict", "verdict": "PASS"}])
    a = classify_run(p)
    assert a.status == OK
    assert not a.needs_rerun
    assert a.surface == "claude_code"
    assert a.arm == "baseline"


def test_claude_allowed_warning_is_ok(tmp_path):
    # "allowed_warning" = served but near the cap → NOT a re-run.
    p = _claude_jsonl(tmp_path, "x__x-1_baseline_run0.jsonl",
                      [_claude_meta(), _rate_event("allowed_warning"), _claude_result()])
    assert classify_run(p).status == OK


def test_claude_rate_limited_rejected(tmp_path):
    p = _claude_jsonl(tmp_path, "x__x-1_baseline_run0.jsonl",
                      [_claude_meta(), _rate_event("rejected"), _claude_result()])
    a = classify_run(p)
    assert a.status == RATE_LIMITED
    assert a.needs_rerun


def test_claude_overage_rejected(tmp_path):
    p = _claude_jsonl(tmp_path, "x__x-1_baseline_run0.jsonl",
                      [_claude_meta(), _rate_event("allowed", overage="rejected"),
                       _claude_result()])
    assert classify_run(p).status == RATE_LIMITED


def test_claude_is_error_is_api_error(tmp_path):
    p = _claude_jsonl(tmp_path, "x__x-1_baseline_run0.jsonl",
                      [_claude_meta(), _claude_result(is_error=True, api_error_status="401")])
    a = classify_run(p)
    assert a.status == API_ERROR
    assert a.needs_rerun


def test_claude_api_error_status_with_ratelimit_text_is_rate_limited(tmp_path):
    p = _claude_jsonl(tmp_path, "x__x-1_baseline_run0.jsonl",
                      [_claude_meta(),
                       _claude_result(is_error=True,
                                      api_error_status="429 Too Many Requests")])
    assert classify_run(p).status == RATE_LIMITED


def test_claude_no_result_line(tmp_path):
    p = _claude_jsonl(tmp_path, "x__x-1_baseline_run0.jsonl",
                      [_claude_meta(), {"type": "assistant", "x": 1}])
    a = classify_run(p)
    assert a.status == NO_RESULT
    assert a.needs_rerun


def test_claude_wall_timeout(tmp_path):
    p = _claude_jsonl(tmp_path, "x__x-1_baseline_run0.jsonl",
                      [_claude_meta(),
                       {"type": "system", "subtype": "wall_timeout", "wall_seconds": 3600}])
    assert classify_run(p).status == WALL_TIMEOUT


def test_claude_max_turns_is_soft(tmp_path):
    p = _claude_jsonl(tmp_path, "x__x-1_baseline_run0.jsonl",
                      [_claude_meta(), _claude_result(subtype="error_max_turns")])
    a = classify_run(p)
    assert a.status == MAX_TURNS
    assert a.is_soft
    assert not a.needs_rerun  # capability outcome, not infra


def test_claude_unknown_subtype_is_api_error(tmp_path):
    p = _claude_jsonl(tmp_path, "x__x-1_baseline_run0.jsonl",
                      [_claude_meta(), _claude_result(subtype="error_during_execution")])
    assert classify_run(p).status == API_ERROR


def test_onlycode_without_codebox_is_mcp_failed(tmp_path):
    p = _claude_jsonl(tmp_path, "x__x-1_onlycode_run0.jsonl",
                      [_claude_meta("onlycode"), _claude_result()])
    a = classify_run(p)
    assert a.status == MCP_FAILED
    assert a.needs_rerun


def test_onlycode_with_codebox_is_ok(tmp_path):
    p = _claude_jsonl(tmp_path, "x__x-1_onlycode_run0.jsonl",
                      [_claude_meta("onlycode"),
                       {"type": "assistant", "tool": "mcp__codebox__execute_code"},
                       _claude_result()])
    assert classify_run(p).status == OK


def test_severity_rate_limited_wins_over_mcp(tmp_path):
    # Both a real rate-limit AND no codebox: report the rate-limit (more actionable).
    p = _claude_jsonl(tmp_path, "x__x-1_onlycode_run0.jsonl",
                      [_claude_meta("onlycode"), _rate_event("rejected"), _claude_result()])
    assert classify_run(p).status == RATE_LIMITED


# ---------------------------------------------------------------------------
# Codex classification
# ---------------------------------------------------------------------------


def _codex_meta(arm: str = "baseline") -> dict:
    return {"type": "meta", "instance_id": "x__x-1", "arm": arm, "run": 0,
            "agent_surface": "codex_cli", "total_cost_usd": 0.05, "num_turns": 3,
            "verdict": "FAIL"}


def test_codex_healthy_is_ok(tmp_path):
    p = _write(tmp_path / "x__x-1_baseline_run0.jsonl",
               ["Reading additional input from stdin...",  # expected non-JSON banner
                _codex_meta(),
                {"type": "thread.started", "thread_id": "t1"},
                {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 2}},
                {"type": "verdict", "verdict": "FAIL"}])
    a = classify_run(p)
    assert a.status == OK
    assert a.surface == "codex_cli"


def test_codex_no_turn_completed_is_no_result(tmp_path):
    p = _write(tmp_path / "x__x-1_baseline_run0.jsonl",
               ["Reading additional input from stdin...", _codex_meta(),
                {"type": "thread.started", "thread_id": "t1"}])
    assert classify_run(p).status == NO_RESULT


def test_codex_error_event_with_ratelimit_is_rate_limited(tmp_path):
    p = _write(tmp_path / "x__x-1_baseline_run0.jsonl",
               [_codex_meta(),
                {"type": "stream_error", "message": "usage limit reached, retry later"},
                {"type": "turn.completed", "usage": {}}])
    assert classify_run(p).status == RATE_LIMITED


def test_codex_generic_error_event_is_api_error(tmp_path):
    p = _write(tmp_path / "x__x-1_baseline_run0.jsonl",
               [_codex_meta(),
                {"type": "error", "message": "something broke"},
                {"type": "turn.completed", "usage": {}}])
    assert classify_run(p).status == API_ERROR


# ---------------------------------------------------------------------------
# File-level edge cases + audit_dir
# ---------------------------------------------------------------------------


def test_empty_file_is_empty(tmp_path):
    p = _write(tmp_path / "x__x-1_baseline_run0.jsonl", [])
    assert classify_run(p).status == EMPTY


def test_surface_inferred_when_meta_missing(tmp_path):
    # No meta line; a result line ⇒ claude.
    p = _write(tmp_path / "x__x-1_baseline_run0.jsonl", [_claude_result()])
    a = classify_run(p)
    assert a.surface == "claude_code"
    assert a.status == OK


def test_audit_dir_skips_underscore_subdirs(tmp_path):
    # Live (top-level) healthy run.
    _write(tmp_path / "x__x-1_baseline_run0.jsonl", [_claude_meta(), _claude_result()])
    # A backup subdir full of failures must NOT be counted.
    backup = tmp_path / "_401_backup_2026-05-27"
    backup.mkdir()
    _write(backup / "y__y-2_baseline_run0.jsonl",
           [_claude_meta(), _claude_result(is_error=True, api_error_status="401")])
    (tmp_path / "_driver_logs").mkdir()
    _write(tmp_path / "_driver_logs" / "z__z-3_baseline_run0.jsonl",
           [_claude_meta(), _claude_result(is_error=True)])

    audits = audit_dir(tmp_path)
    assert len(audits) == 1
    assert audits[0].instance_id == "x__x-1"
    assert audits[0].status == OK


def test_audit_dir_filters_non_run_jsonl(tmp_path):
    _write(tmp_path / "x__x-1_baseline_run0.jsonl", [_claude_meta(), _claude_result()])
    _write(tmp_path / "predictions.jsonl", [{"type": "junk"}])  # not a run transcript
    audits = audit_dir(tmp_path)
    assert {a.instance_id for a in audits} == {"x__x-1"}


def test_verdict_read_from_test_txt(tmp_path):
    p = _write(tmp_path / "x__x-1_baseline_run0.jsonl", [_claude_meta(), _claude_result()])
    (tmp_path / "x__x-1_baseline_run0_test.txt").write_text("some log\nPASS\n")
    assert classify_run(p).verdict == "PASS"
