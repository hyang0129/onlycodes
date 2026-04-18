"""Tests for ``swebench.analyze.extractor`` (Stage 1 mechanical extractor).

Fixtures live in ``tests/fixtures/logs/``: two trimmed real logs (a small
django run and a larger xarray run), plus two synthetic edge cases
(baseline-only orphan and an empty ARM_CRASH transcript).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from swebench.analyze.extractor import (
    CODEBOX_TOOL_NAME,
    FLAG_ARM_CRASH_NO_OUTPUT,
    TRIAGE_TOP_PERCENTILE,
    TURN_DEFINITION,
    codebox_code_hashes,
    codebox_pairwise_jaccard,
    count_turns,
    extract,
    extract_total_cost,
    iter_records,
    jaccard_similarity,
    md5_hex,
    triage_rank,
)

FIXTURES = Path(__file__).parent / "fixtures" / "logs"
DJANGO_ONLYCODE = FIXTURES / "django__django-16379_onlycode_run1.jsonl"
DJANGO_BASELINE = FIXTURES / "django__django-16379_baseline_run1.jsonl"
XARRAY_ONLYCODE = FIXTURES / "pydata__xarray-7229_onlycode_run1.jsonl"
ORPHAN_BASELINE = FIXTURES / "orphan_only_baseline_run1.jsonl"
ARM_CRASH = FIXTURES / "arm_crash_onlycode_run1.jsonl"


# ---------------------------------------------------------------------------
# Contract / docstring
# ---------------------------------------------------------------------------


def test_turn_definition_pinned():
    assert TURN_DEFINITION == "unique tool_use.id across all assistant records"


def test_module_docstring_pins_adr():
    from swebench.analyze import extractor

    assert extractor.__doc__ is not None
    assert "tool_use.id" in extractor.__doc__
    assert "ADR Q1" in extractor.__doc__


# ---------------------------------------------------------------------------
# iter_records
# ---------------------------------------------------------------------------


def test_iter_records_yields_dicts():
    recs = list(iter_records(DJANGO_ONLYCODE))
    assert len(recs) > 0
    assert all(isinstance(r, dict) for r in recs)


def test_iter_records_skips_blank_and_bad(tmp_path):
    p = tmp_path / "mixed.jsonl"
    p.write_text('{"a": 1}\n\n{not json}\n{"b": 2}\n')
    recs = list(iter_records(p))
    assert recs == [{"a": 1}, {"b": 2}]


# ---------------------------------------------------------------------------
# count_turns (ADR Q1)
# ---------------------------------------------------------------------------


def test_count_turns_on_django_onlycode():
    recs = list(iter_records(DJANGO_ONLYCODE))
    # Real log: 3 codebox calls visible in the trimmed fixture.
    assert count_turns(recs) == 3


def test_count_turns_deduplicates_ids():
    recs = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "dup", "name": "X"},
        ]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "dup", "name": "X"},
        ]}},
    ]
    assert count_turns(recs) == 1


def test_count_turns_ignores_non_assistant_records():
    recs = [
        {"type": "user", "message": {"content": [
            {"type": "tool_use", "id": "ignored", "name": "X"},
        ]}},
        {"type": "system", "message": {"content": []}},
        {"type": "result", "num_turns": 42},
    ]
    assert count_turns(recs) == 0


def test_count_turns_ignores_text_and_thinking():
    recs = [
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "hi"},
            {"type": "thinking", "thinking": "hmm"},
        ]}},
    ]
    assert count_turns(recs) == 0


def test_count_turns_handles_missing_content():
    recs = [
        {"type": "assistant"},
        {"type": "assistant", "message": {}},
        {"type": "assistant", "message": {"content": None}},
    ]
    assert count_turns(recs) == 0


def test_count_turns_ignores_tool_use_without_id():
    recs = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "X"},
        ]}},
    ]
    assert count_turns(recs) == 0


def test_count_turns_deterministic_on_repeat():
    recs = list(iter_records(XARRAY_ONLYCODE))
    a = count_turns(recs)
    b = count_turns(recs)
    assert a == b and a > 0


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------


def test_extract_total_cost_from_fixture():
    recs = list(iter_records(DJANGO_ONLYCODE))
    cost = extract_total_cost(recs)
    assert cost is not None
    assert cost > 0


def test_extract_total_cost_missing_returns_none():
    assert extract_total_cost([{"type": "assistant"}]) is None


def test_extract_total_cost_ignores_bad_values():
    recs = [{"type": "result", "total_cost_usd": "not-a-number"}]
    assert extract_total_cost(recs) is None


def test_extract_total_cost_takes_last_result():
    recs = [
        {"type": "result", "total_cost_usd": 0.1},
        {"type": "result", "total_cost_usd": 0.5},
    ]
    assert extract_total_cost(recs) == 0.5


# ---------------------------------------------------------------------------
# MD5 + codebox_code_hashes
# ---------------------------------------------------------------------------


def test_md5_hex_matches_stdlib():
    assert md5_hex("hello") == hashlib.md5(b"hello").hexdigest()


def test_codebox_code_hashes_real_log():
    recs = list(iter_records(DJANGO_ONLYCODE))
    hashes = codebox_code_hashes(recs)
    assert len(hashes) == 3
    assert all(len(h) == 32 for h in hashes)


def test_codebox_code_hashes_skips_non_codebox_tools():
    recs = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "a", "name": "Read", "input": {"file_path": "/x"}},
            {"type": "tool_use", "id": "b", "name": CODEBOX_TOOL_NAME, "input": {"code": "print(1)"}},
        ]}}
    ]
    out = codebox_code_hashes(recs)
    assert out == [md5_hex("print(1)")]


def test_codebox_code_hashes_handles_missing_code():
    recs = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "a", "name": CODEBOX_TOOL_NAME, "input": {}},
        ]}}
    ]
    assert codebox_code_hashes(recs) == [md5_hex("")]


# ---------------------------------------------------------------------------
# Jaccard
# ---------------------------------------------------------------------------


def test_jaccard_identical_is_one():
    s = "one two three four five six seven"
    assert jaccard_similarity(s, s) == 1.0


def test_jaccard_disjoint_is_zero():
    assert jaccard_similarity("a b c d e f g", "h i j k l m n") == 0.0


def test_jaccard_empty_inputs():
    assert jaccard_similarity("", "") == 0.0


def test_jaccard_short_inputs_use_full_tuple():
    # Short inputs (< 5 words) should still register some similarity.
    assert jaccard_similarity("a b c", "a b c") == 1.0
    assert jaccard_similarity("a b c", "x y z") == 0.0


def test_codebox_pairwise_jaccard_empty_when_single_turn():
    recs = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "a", "name": CODEBOX_TOOL_NAME, "input": {"code": "x"}},
        ]}}
    ]
    assert codebox_pairwise_jaccard(recs) == []


def test_codebox_pairwise_jaccard_multi_turn():
    recs = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "a", "name": CODEBOX_TOOL_NAME,
             "input": {"code": "one two three four five"}},
            {"type": "tool_use", "id": "b", "name": CODEBOX_TOOL_NAME,
             "input": {"code": "one two three four five"}},
            {"type": "tool_use", "id": "c", "name": CODEBOX_TOOL_NAME,
             "input": {"code": "six seven eight nine ten"}},
        ]}}
    ]
    scores = codebox_pairwise_jaccard(recs)
    assert len(scores) == 2
    assert scores[0] == 1.0
    assert scores[1] == 0.0


# ---------------------------------------------------------------------------
# extract (end to end)
# ---------------------------------------------------------------------------


def test_extract_on_django_returns_expected_shape():
    out = extract(DJANGO_ONLYCODE)
    assert set(out.keys()) == {
        "path", "turns", "total_cost_usd", "codebox_turns",
        "codebox_code_md5", "codebox_pairwise_jaccard", "mechanical_flags",
    }
    assert out["turns"] == 3
    assert out["codebox_turns"] == 3
    assert out["total_cost_usd"] is not None and out["total_cost_usd"] > 0
    assert len(out["codebox_code_md5"]) == 3
    assert len(out["codebox_pairwise_jaccard"]) == 2
    assert out["mechanical_flags"] == []


def test_extract_on_xarray_largest_sample():
    out = extract(XARRAY_ONLYCODE)
    assert out["turns"] >= 1
    assert out["codebox_turns"] >= 0
    assert isinstance(out["codebox_code_md5"], list)


def test_extract_baseline_has_no_codebox_turns():
    out = extract(DJANGO_BASELINE)
    assert out["turns"] > 0  # Edit/Read tool calls do contribute
    assert out["codebox_turns"] == 0
    assert out["codebox_code_md5"] == []


def test_extract_arm_crash_flagged():
    out = extract(ARM_CRASH)
    assert out["turns"] == 0
    assert FLAG_ARM_CRASH_NO_OUTPUT in out["mechanical_flags"]


def test_extract_json_serializable():
    out = extract(DJANGO_ONLYCODE)
    # Must survive json.dumps for the ADR Q4 sidecar artifact.
    s = json.dumps(out)
    assert "turns" in s


def test_extract_does_not_raise_on_bad_file(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text("this is not json\n\n{also not}\n")
    out = extract(p)
    assert out["turns"] == 0
    assert FLAG_ARM_CRASH_NO_OUTPUT in out["mechanical_flags"]


# ---------------------------------------------------------------------------
# triage_rank
# ---------------------------------------------------------------------------


def test_triage_rank_empty():
    assert triage_rank([]) == []


def test_triage_rank_orphan_first():
    metrics = [
        {"task_id": "t1", "arm": "onlycode", "run": 1, "turns": 5, "total_cost_usd": 1.0},
        {"task_id": "t1", "arm": "baseline", "run": 1, "turns": 5, "total_cost_usd": 1.0},
        {"task_id": "t2", "arm": "baseline", "run": 1, "turns": 3, "total_cost_usd": 0.5},
    ]
    ranked = triage_rank(metrics)
    # The orphan (t2 baseline without onlycode pair) must be first.
    assert ranked[0]["task_id"] == "t2"
    assert FLAG_ARM_CRASH_NO_OUTPUT in ranked[0]["mechanical_flags"]


def test_triage_rank_flag_preserved_beats_high_turns():
    metrics = [
        # t1 has a matching pair across arms, so it is NOT orphan-flagged.
        {"task_id": "t1", "arm": "a", "turns": 100, "total_cost_usd": 10.0},
        {"task_id": "t1", "arm": "b", "turns": 100, "total_cost_usd": 10.0},
        # t2 carries an explicit flag from the extractor (empty transcript).
        {"task_id": "t2", "arm": "a", "turns": 1, "total_cost_usd": 0.0,
         "mechanical_flags": [FLAG_ARM_CRASH_NO_OUTPUT]},
        {"task_id": "t2", "arm": "b", "turns": 1, "total_cost_usd": 0.0,
         "mechanical_flags": [FLAG_ARM_CRASH_NO_OUTPUT]},
    ]
    ranked = triage_rank(metrics)
    assert ranked[0]["task_id"] == "t2"


def test_triage_rank_sorts_by_turns_then_cost():
    metrics = [
        {"task_id": "t1", "arm": "a", "turns": 5, "total_cost_usd": 1.0},
        {"task_id": "t2", "arm": "a", "turns": 10, "total_cost_usd": 0.1},
        {"task_id": "t3", "arm": "a", "turns": 10, "total_cost_usd": 5.0},
        {"task_id": "t4", "arm": "a", "turns": 1, "total_cost_usd": 0.0},
    ]
    # Note: single-arm rows will all be flagged as orphans; test without pairing
    # so we override: use matched arms to keep them un-flagged.
    metrics = [
        {"task_id": "t1", "arm": "a", "turns": 5, "total_cost_usd": 1.0},
        {"task_id": "t1", "arm": "b", "turns": 5, "total_cost_usd": 1.0},
        {"task_id": "t2", "arm": "a", "turns": 10, "total_cost_usd": 0.1},
        {"task_id": "t2", "arm": "b", "turns": 10, "total_cost_usd": 5.0},
    ]
    ranked = triage_rank(metrics)
    # Highest turns should come first.
    assert ranked[0]["turns"] == 10


def test_triage_rank_missing_keys_does_not_raise():
    metrics = [
        {"turns": 3},
        {"total_cost_usd": 1.0},
        {},
    ]
    # None have task_id/arm, so orphan detection skips them.
    ranked = triage_rank(metrics)
    assert len(ranked) == 3


def test_triage_rank_bad_values_default_safely():
    metrics = [
        {"task_id": "t1", "arm": "a", "turns": "garbage", "total_cost_usd": "nope"},
        {"task_id": "t1", "arm": "b", "turns": None, "total_cost_usd": None},
    ]
    ranked = triage_rank(metrics)
    assert len(ranked) == 2


def test_triage_top_percentile_is_twenty_percent():
    assert TRIAGE_TOP_PERCENTILE == 0.20


def test_orphan_baseline_only_fixture():
    # Orphan fixture has only a baseline log — simulate the pairing pass.
    out = extract(ORPHAN_BASELINE)
    metrics = [dict(out, task_id="t-orphan", arm="baseline", run=1)]
    ranked = triage_rank(metrics)
    assert FLAG_ARM_CRASH_NO_OUTPUT in ranked[0]["mechanical_flags"]
