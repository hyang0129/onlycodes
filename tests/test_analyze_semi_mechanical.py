"""Offline tests for the semi-mechanical pathology stage.

Covers:
  - extractor registry (register/iter; idempotent load; reset for tests)
  - filter-only behavior (no LLM call when filter returns empty)
  - dry-run output: excerpts + composed prompt without subprocess
  - CLI ``--stage semi-mechanical`` discovery + integration
  - ``_reviewer_to_sidecar`` produces schema-valid output

No test here invokes the real ``claude`` binary.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from swebench.analyze import analyze_command, registry, semi_mechanical
from swebench.analyze.semi_mechanical import (
    Extractor,
    _reset_bundled_for_testing,
    _reset_registry_for_testing,
    _reviewer_to_sidecar,
    iter_extractors,
    load_bundled_extractors,
    register,
    run_semi_mechanical,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():
    """Each test starts with an empty extractor registry.

    Delegates to the module-owned reset helpers so the test file does not
    reach into semi_mechanical's private globals.
    """
    def _scrub():
        _reset_registry_for_testing()
        _reset_bundled_for_testing()
    _scrub()
    yield
    _scrub()


# ---------------------------------------------------------------------------
# Registry API
# ---------------------------------------------------------------------------


def test_register_adds_extractor() -> None:
    register("foo", target_pattern_id="some_pathology",
             filter_fn=lambda p: [], system_prompt="sys")
    items = list(iter_extractors())
    assert len(items) == 1
    assert items[0].extractor_id == "foo"
    assert items[0].target_pattern_id == "some_pathology"


def test_register_rejects_duplicate() -> None:
    register("foo", target_pattern_id="x", filter_fn=lambda p: [], system_prompt="s")
    with pytest.raises(ValueError, match="already registered"):
        register("foo", target_pattern_id="y", filter_fn=lambda p: [], system_prompt="s")


def test_load_bundled_extractors_is_idempotent() -> None:
    load_bundled_extractors()
    first = [e.extractor_id for e in iter_extractors()]
    load_bundled_extractors()  # second call — must not raise duplicate error
    second = [e.extractor_id for e in iter_extractors()]
    assert first == second
    assert "git_archaeology" in first
    assert "iteration_stall" in first


# ---------------------------------------------------------------------------
# Sidecar shape
# ---------------------------------------------------------------------------


def test_reviewer_to_sidecar_validates_flagged() -> None:
    ex = Extractor("fake", "some_pathology", lambda p: [], "sys")
    reviewer = {
        "flagged": True,
        "confidence": "high",
        "reasoning": "the agent did X",
        "key_evidence": ["snippet 1", "snippet 2"],
    }
    sc = _reviewer_to_sidecar(
        log_ref="log_a", arm="baseline", extractor=ex,
        reviewer=reviewer, excerpts=["raw excerpt"],
    )
    errs = registry.validate_subagent_output(sc)
    assert errs == [], errs
    assert sc["findings"][0]["candidate_id"] == "some_pathology"
    assert sc["findings"][0]["confidence"] == "high"
    # Severity must mirror reviewer confidence — preserves strength signal
    # for Stage 3 synthesis.
    assert sc["findings"][0]["severity"] == "high"


@pytest.mark.parametrize("confidence,expected_severity", [
    ("high", "high"),
    ("medium", "medium"),
    ("low", "low"),
])
def test_reviewer_to_sidecar_severity_mirrors_confidence(
    confidence: str, expected_severity: str,
) -> None:
    """Each flagged finding's severity must equal the reviewer's confidence."""
    ex = Extractor("fake", "some_pathology", lambda p: [], "sys")
    sc = _reviewer_to_sidecar(
        log_ref="x", arm="baseline", extractor=ex,
        reviewer={"flagged": True, "confidence": confidence,
                  "reasoning": "r", "key_evidence": ["e"]},
        excerpts=["raw"],
    )
    assert sc["findings"][0]["severity"] == expected_severity
    # Invariant: severity MUST NOT be silently defaulted to "medium" when
    # the reviewer expressed a different confidence level.
    if confidence != "medium":
        assert sc["findings"][0]["severity"] != "medium"


def test_reviewer_to_sidecar_validates_unflagged() -> None:
    ex = Extractor("fake", "p", lambda p: [], "sys")
    sc = _reviewer_to_sidecar(
        log_ref="log_a", arm="tool_rich", extractor=ex,
        reviewer={"flagged": False, "confidence": "low", "reasoning": "no"},
        excerpts=["raw"],
    )
    errs = registry.validate_subagent_output(sc)
    assert errs == [], errs
    assert sc["findings"] == []
    assert sc["arm"] == "tool_rich"  # artifact arm accepted


def test_reviewer_to_sidecar_accepts_artifact_arm() -> None:
    ex = Extractor("fake", "p", lambda p: [], "sys")
    for arm in ("tool_rich", "code_only"):
        sc = _reviewer_to_sidecar(
            log_ref="x", arm=arm, extractor=ex,
            reviewer={"flagged": False, "confidence": "low", "reasoning": "no"},
            excerpts=[],
        )
        assert registry.validate_subagent_output(sc) == []


# ---------------------------------------------------------------------------
# Stage driver — dry-run and no-match paths
# ---------------------------------------------------------------------------


def _write_fake_jsonl(path: Path) -> None:
    path.write_text(
        json.dumps({"type": "assistant", "text": "hello"}) + "\n"
        + json.dumps({"type": "result", "total_cost_usd": 0.01, "num_turns": 1}) + "\n"
    )


def test_run_semi_mechanical_returns_empty_when_no_extractors(tmp_path: Path) -> None:
    # Registry is empty (autouse fixture cleared it).
    metrics = [{"log_ref": "foo", "arm": "baseline", "jsonl_path": str(tmp_path / "foo.jsonl")}]
    matched = run_semi_mechanical(
        metrics=metrics, analysis_root=tmp_path / "_analysis", concurrency=2,
        force=False, dry_run=True,
    )
    assert matched == set()


def test_run_semi_mechanical_no_match_produces_no_sidecar(tmp_path: Path) -> None:
    jsonl = tmp_path / "log.jsonl"
    _write_fake_jsonl(jsonl)
    register("never", target_pattern_id="p",
             filter_fn=lambda p: [], system_prompt="s")
    out_root = tmp_path / "_analysis"
    matched = run_semi_mechanical(
        metrics=[{"log_ref": "log", "arm": "baseline", "jsonl_path": str(jsonl)}],
        analysis_root=out_root, concurrency=1, force=False, dry_run=False,
    )
    assert matched == set()
    assert not (out_root / "semi_mechanical").exists() or \
        list((out_root / "semi_mechanical").glob("*.json")) == []


def test_run_semi_mechanical_dry_run_emits_prompt_and_excerpts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    jsonl = tmp_path / "log.jsonl"
    _write_fake_jsonl(jsonl)
    register("fires", target_pattern_id="tool_call_loop",
             filter_fn=lambda p: ["excerpt body 1"], system_prompt="SYS")
    out_root = tmp_path / "_analysis"
    matched = run_semi_mechanical(
        metrics=[{"log_ref": "log", "arm": "baseline", "jsonl_path": str(jsonl)}],
        analysis_root=out_root, concurrency=1, force=False, dry_run=True,
    )
    captured = capsys.readouterr().out
    assert "DRY RUN semi-mechanical" in captured
    assert "extractor=fires" in captured
    assert "excerpt body 1" in captured
    # Dry-run: no sidecar on disk.
    assert not (out_root / "semi_mechanical").exists()
    # Dry-run still reports matches so Stage 2 can skip.
    assert matched == {"log"}


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def _invoke(args: list[str]):
    runner = CliRunner()
    return runner.invoke(analyze_command, args, catch_exceptions=False)


def test_pathology_help_includes_semi_mechanical_stage() -> None:
    result = _invoke(["pathology", "--help"])
    assert result.exit_code == 0, result.output
    assert "semi-mechanical" in result.output


def test_pathology_stage_semi_mechanical_dry_run(tmp_path: Path) -> None:
    """``--stage semi-mechanical --dry-run`` walks logs + extractors."""
    work = tmp_path / "results_swebench"
    work.mkdir()
    jsonl = work / "django__django-16379_baseline_run1.jsonl"
    # One assistant turn with a Bash 'git log' call to fire git_archaeology.
    jsonl.write_text("\n".join([
        json.dumps({
            "type": "assistant",
            "message": {"content": [{
                "type": "tool_use", "id": "t1", "name": "Bash",
                "input": {"command": "git log --all --oneline"}
            }]}
        }),
        json.dumps({
            "type": "user",
            "message": {"content": [{
                "type": "tool_result", "tool_use_id": "t1",
                "content": "abc123 commit"
            }]}
        }),
        json.dumps({"type": "result", "total_cost_usd": 0.01, "num_turns": 1}),
    ]) + "\n")

    result = _invoke([
        "pathology",
        "--results-dir", str(work),
        "--stage", "semi-mechanical",
        "--dry-run",
        "--run-id", "t1",
    ])
    assert result.exit_code == 0, result.output
    assert "DRY RUN semi-mechanical" in result.output
    assert "git_archaeology" in result.output
    # No sidecars in dry-run.
    assert not (work / "_analysis" / "t1" / "semi_mechanical").exists()
