"""Unit tests for ``swebench.analyze.registry``.

All writes go to ``tmp_path``; the autouse guard in ``conftest.py`` asserts
the repo-root ``patterns.json`` is never touched by the test suite.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from swebench.analyze import registry


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _seed_registry() -> dict:
    return {"version": 1, "patterns": []}


def _make_finding(
    cid: str = "amnesiac_retry",
    *,
    log_ref: str = "django__django-11964_onlycode_run1",
    arm: str = "onlycode",
    turn: int = 5,
    excerpt: str = "python -c 'import django'",
    description: str = "agent re-ran same command repeatedly",
) -> dict:
    return {
        "candidate_id": cid,
        "description": description,
        "evidence_refs": [{"turn": turn, "excerpt": excerpt}],
        "log_ref": log_ref,
        "arm": arm,
    }


def _make_subagent_output(
    *,
    log_ref: str = "django__django-11964_onlycode_run1",
    arm: str = "onlycode",
    cid: str = "amnesiac_retry",
    extras: dict | None = None,
) -> dict:
    base = {
        "log_ref": log_ref,
        "arm": arm,
        "findings": [
            {
                "candidate_id": cid,
                "description": "x",
                "evidence_refs": [{"turn": 1, "excerpt": "code"}],
                "severity": "high",
                "confidence": "high",
            }
        ],
    }
    if extras:
        base.update(extras)
    return base


# ---------------------------------------------------------------------------
# load_patterns
# ---------------------------------------------------------------------------


def test_load_patterns_happy(tmp_path: Path) -> None:
    p = tmp_path / "patterns.json"
    p.write_text(json.dumps(_seed_registry()))
    data, err = registry.load_patterns(p)
    assert err is None
    assert data == _seed_registry()


def test_load_patterns_missing_file(tmp_path: Path) -> None:
    data, err = registry.load_patterns(tmp_path / "nope.json")
    assert data is None
    assert err and "does not exist" in err


def test_load_patterns_malformed_json(tmp_path: Path) -> None:
    p = tmp_path / "patterns.json"
    p.write_text("not-json{{")
    data, err = registry.load_patterns(p)
    assert data is None
    assert err and "JSON decode" in err


def test_load_patterns_schema_fail(tmp_path: Path) -> None:
    p = tmp_path / "patterns.json"
    p.write_text(json.dumps({"version": 99, "patterns": []}))
    data, err = registry.load_patterns(p)
    assert data is None
    assert err and "unsupported version" in err


def test_load_patterns_unknown_top_key(tmp_path: Path) -> None:
    p = tmp_path / "patterns.json"
    p.write_text(json.dumps({"version": 1, "patterns": [], "extra": 1}))
    data, err = registry.load_patterns(p)
    assert data is None
    assert err and "unknown top-level keys" in err


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_empty_ok() -> None:
    assert registry.validate(_seed_registry()) == []


def test_validate_not_dict() -> None:
    errs = registry.validate([])
    assert errs and "object" in errs[0]


def test_validate_full_pattern_ok() -> None:
    data = {
        "version": 1,
        "patterns": [
            {
                "id": "amnesiac_retry",
                "description": "x",
                "evidence_refs": [
                    {"log_ref": "a", "run_id": "r", "turn": 1, "excerpt": "e"}
                ],
                "frequency": 1,
                "arm_distribution": {"baseline": 0, "onlycode": 1},
                "first_seen_run_id": "r",
                "last_seen_run_id": "r",
            }
        ],
    }
    assert registry.validate(data) == []


def test_validate_bad_pattern_id() -> None:
    data = {
        "version": 1,
        "patterns": [
            {
                "id": "BadID!",
                "description": "x",
                "evidence_refs": [],
                "frequency": 0,
                "arm_distribution": {"baseline": 0, "onlycode": 0},
                "first_seen_run_id": "r",
                "last_seen_run_id": "r",
            }
        ],
    }
    errs = registry.validate(data)
    assert any("invalid slug" in e for e in errs)


def test_validate_pattern_missing_key() -> None:
    data = {
        "version": 1,
        "patterns": [{"id": "ok_id"}],
    }
    errs = registry.validate(data)
    assert any("missing keys" in e for e in errs)


def test_validate_evidence_ref_excerpt_too_long() -> None:
    data = {
        "version": 1,
        "patterns": [
            {
                "id": "foo",
                "description": "x",
                "evidence_refs": [
                    {
                        "log_ref": "a",
                        "run_id": "r",
                        "turn": 1,
                        "excerpt": "x" * 241,
                    }
                ],
                "frequency": 0,
                "arm_distribution": {"baseline": 0, "onlycode": 0},
                "first_seen_run_id": "r",
                "last_seen_run_id": "r",
            }
        ],
    }
    errs = registry.validate(data)
    assert any("240" in e for e in errs)


# ---------------------------------------------------------------------------
# validate_subagent_output
# ---------------------------------------------------------------------------


def test_validate_subagent_ok() -> None:
    assert registry.validate_subagent_output(_make_subagent_output()) == []


def test_validate_subagent_unknown_top_key() -> None:
    data = _make_subagent_output(extras={"extra": 1})
    errs = registry.validate_subagent_output(data)
    assert any("unknown top-level keys" in e for e in errs)


def test_validate_subagent_bad_arm() -> None:
    data = _make_subagent_output(arm="control")
    errs = registry.validate_subagent_output(data)
    assert any("arm must be" in e for e in errs)


def test_validate_subagent_notes_wrong_type() -> None:
    data = _make_subagent_output(extras={"notes": 42})
    errs = registry.validate_subagent_output(data)
    assert any("notes" in e for e in errs)


def test_validate_subagent_finding_missing_key() -> None:
    data = _make_subagent_output()
    del data["findings"][0]["severity"]
    errs = registry.validate_subagent_output(data)
    assert any("missing keys" in e for e in errs)


def test_validate_subagent_finding_bad_candidate_id() -> None:
    data = _make_subagent_output()
    data["findings"][0]["candidate_id"] = "X"
    errs = registry.validate_subagent_output(data)
    assert any("invalid slug" in e for e in errs)


def test_validate_subagent_finding_unknown_key() -> None:
    data = _make_subagent_output()
    data["findings"][0]["extra"] = 1
    errs = registry.validate_subagent_output(data)
    assert any("unknown keys" in e for e in errs)


def test_validate_subagent_missing_findings() -> None:
    data = {"log_ref": "x", "arm": "onlycode"}
    errs = registry.validate_subagent_output(data)
    assert any("findings" in e for e in errs)


# ---------------------------------------------------------------------------
# write_patterns (atomic) + deterministic sort
# ---------------------------------------------------------------------------


def test_write_patterns_atomic_and_sorted(tmp_path: Path) -> None:
    p = tmp_path / "patterns.json"
    data = {
        "version": 1,
        "patterns": [
            {
                "id": "zzz",
                "description": "z",
                "evidence_refs": [],
                "frequency": 0,
                "arm_distribution": {"baseline": 0, "onlycode": 0},
                "first_seen_run_id": "r",
                "last_seen_run_id": "r",
            },
            {
                "id": "aaa",
                "description": "a",
                "evidence_refs": [],
                "frequency": 0,
                "arm_distribution": {"baseline": 0, "onlycode": 0},
                "first_seen_run_id": "r",
                "last_seen_run_id": "r",
            },
        ],
    }
    registry.write_patterns(p, data)
    written = json.loads(p.read_text())
    ids = [pat["id"] for pat in written["patterns"]]
    assert ids == ["aaa", "zzz"]
    # No stray tempfiles left behind.
    leftover = [f for f in os.listdir(tmp_path) if f.startswith(".patterns-")]
    assert leftover == []


def test_write_patterns_crash_mid_write_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If ``os.replace`` fails mid-write, the destination must be untouched."""
    p = tmp_path / "patterns.json"
    # Seed with a known-good file first.
    seed = _seed_registry()
    registry.write_patterns(p, seed)
    original = p.read_bytes()

    def _boom(src, dst):  # noqa: ARG001
        raise OSError("simulated crash")

    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(OSError, match="simulated crash"):
        registry.write_patterns(p, {"version": 1, "patterns": []})

    # Original file is intact.
    assert p.read_bytes() == original
    # Tempfile was cleaned up.
    leftover = [f for f in os.listdir(tmp_path) if f.startswith(".patterns-")]
    assert leftover == []


def test_write_patterns_creates_parent_dir(tmp_path: Path) -> None:
    p = tmp_path / "nested" / "dir" / "patterns.json"
    registry.write_patterns(p, _seed_registry())
    assert p.exists()


# ---------------------------------------------------------------------------
# merge (pure)
# ---------------------------------------------------------------------------


def test_merge_new_id_insertion() -> None:
    existing = _seed_registry()
    out = registry.merge(existing, [_make_finding()], run_id="r1")
    assert len(out["patterns"]) == 1
    pat = out["patterns"][0]
    assert pat["id"] == "amnesiac_retry"
    assert pat["frequency"] == 1
    assert pat["arm_distribution"] == {"baseline": 0, "onlycode": 1}
    assert pat["first_seen_run_id"] == "r1"
    assert pat["last_seen_run_id"] == "r1"
    assert existing == _seed_registry()  # pure: not mutated


def test_merge_same_id_collision_increments() -> None:
    existing = _seed_registry()
    r1 = registry.merge(existing, [_make_finding(turn=1)], run_id="r1")
    r2 = registry.merge(
        r1,
        [_make_finding(turn=2, log_ref="other_onlycode_run1")],
        run_id="r2",
    )
    pat = r2["patterns"][0]
    assert pat["frequency"] == 2
    assert pat["arm_distribution"]["onlycode"] == 2
    assert pat["first_seen_run_id"] == "r1"
    assert pat["last_seen_run_id"] == "r2"
    assert len(pat["evidence_refs"]) == 2


def test_merge_evidence_dedup_by_tuple() -> None:
    existing = _seed_registry()
    r1 = registry.merge(existing, [_make_finding(turn=5)], run_id="r1")
    # Same (log_ref, run_id, turn) — should be de-duped.
    r2 = registry.merge(r1, [_make_finding(turn=5)], run_id="r1")
    pat = r2["patterns"][0]
    assert pat["frequency"] == 1
    assert len(pat["evidence_refs"]) == 1


def test_merge_evidence_cap_at_20() -> None:
    existing = _seed_registry()
    current = existing
    for turn in range(25):
        current = registry.merge(
            current,
            [_make_finding(turn=turn, log_ref=f"log_{turn}")],
            run_id="r1",
        )
    pat = current["patterns"][0]
    assert len(pat["evidence_refs"]) == registry.MAX_EVIDENCE_REFS
    # Most-recent-first: the last added (turn=24) must be present.
    assert pat["evidence_refs"][0]["turn"] == 24
    # Oldest (turn=0) must have been dropped.
    assert all(r["turn"] != 0 for r in pat["evidence_refs"])


def test_merge_arm_distribution_sums_both_arms() -> None:
    existing = _seed_registry()
    findings = [
        _make_finding(arm="baseline", log_ref="b1", turn=1),
        _make_finding(arm="baseline", log_ref="b2", turn=1),
        _make_finding(arm="onlycode", log_ref="o1", turn=1),
    ]
    out = registry.merge(existing, findings, run_id="r1")
    pat = out["patterns"][0]
    assert pat["arm_distribution"] == {"baseline": 2, "onlycode": 1}
    assert pat["frequency"] == 3


def test_merge_first_writer_wins_description() -> None:
    existing = _seed_registry()
    r1 = registry.merge(
        existing,
        [_make_finding(description="first description")],
        run_id="r1",
    )
    r2 = registry.merge(
        r1,
        [_make_finding(log_ref="other", turn=9, description="DIFFERENT description")],
        run_id="r2",
    )
    assert r2["patterns"][0]["description"] == "first description"


def test_merge_sorts_patterns_by_id() -> None:
    existing = _seed_registry()
    findings = [
        _make_finding(cid="zzz_last", log_ref="a", turn=1),
        _make_finding(cid="aaa_first", log_ref="b", turn=1),
        _make_finding(cid="mmm_mid", log_ref="c", turn=1),
    ]
    out = registry.merge(existing, findings, run_id="r1")
    assert [p["id"] for p in out["patterns"]] == ["aaa_first", "mmm_mid", "zzz_last"]


def test_merge_is_pure_no_mutation() -> None:
    existing = _seed_registry()
    snapshot = json.dumps(existing, sort_keys=True)
    findings = [_make_finding()]
    findings_snapshot = json.dumps(findings, sort_keys=True)
    registry.merge(existing, findings, run_id="r1")
    assert json.dumps(existing, sort_keys=True) == snapshot
    assert json.dumps(findings, sort_keys=True) == findings_snapshot


def test_merge_accepts_none_existing() -> None:
    out = registry.merge(None, [_make_finding()], run_id="r1")  # type: ignore[arg-type]
    assert out["version"] == 1
    assert len(out["patterns"]) == 1


# ---------------------------------------------------------------------------
# flatten_findings
# ---------------------------------------------------------------------------


def test_flatten_findings_carries_log_ref_and_arm() -> None:
    outputs = [
        {
            "log_ref": "X_onlycode_run1",
            "arm": "onlycode",
            "findings": [
                {
                    "candidate_id": "cid1",
                    "description": "d",
                    "evidence_refs": [{"turn": 1, "excerpt": "e"}],
                    "severity": "low",
                    "confidence": "low",
                }
            ],
        }
    ]
    flat = registry.flatten_findings(outputs)
    assert len(flat) == 1
    assert flat[0]["log_ref"] == "X_onlycode_run1"
    assert flat[0]["arm"] == "onlycode"
