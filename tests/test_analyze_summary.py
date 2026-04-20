"""Characterization tests for `python -m swebench analyze` summary behaviour.

Pins the current tabulated stdout and --out CSV output byte-for-byte against
synthetic fixtures, so future refactors of swebench/analyze.py cannot silently
change the observable summary contract. No production code is exercised beyond
importing `analyze_command` — the tests are fully offline, need no `claude`
binary, and run in well under 2s.

Sub-issue #69 of epic #62 (log analysis pipeline).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from swebench.analyze import analyze_command


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "analyze"


def _load_golden(name: str) -> str:
    return (FIXTURES_DIR / name).read_text()


def _render_csv_golden(name: str, fixture_dir: Path) -> str:
    """Load a golden CSV and substitute the {FIXTURE_DIR} placeholder."""
    return _load_golden(name).replace("{FIXTURE_DIR}", str(fixture_dir))


def _run(results_dir: Path, out_path: Path | None = None):
    runner = CliRunner()
    args = ["summary", "--results-dir", str(results_dir)]
    if out_path is not None:
        args += ["--out", str(out_path)]
    return runner.invoke(analyze_command, args, catch_exceptions=False)


# ---------------------------------------------------------------------------
# Happy path: baseline + onlycode arms, single run.
# ---------------------------------------------------------------------------


def test_both_arms_stdout_is_pinned():
    fixture_dir = FIXTURES_DIR / "both_arms"
    result = _run(fixture_dir)
    assert result.exit_code == 0, result.output

    expected = _load_golden("both_arms_stdout.golden.txt")
    assert result.output == expected


def test_both_arms_csv_is_pinned(tmp_path: Path):
    fixture_dir = FIXTURES_DIR / "both_arms"
    out_path = tmp_path / "summary.csv"
    result = _run(fixture_dir, out_path)
    assert result.exit_code == 0, result.output

    expected_csv = _render_csv_golden("both_arms.golden.csv", fixture_dir)
    # CSV writer on POSIX uses \r\n for DictWriter by default via csv module;
    # read as bytes normalized text and compare verbatim.
    actual = out_path.read_text()
    assert actual == expected_csv


# ---------------------------------------------------------------------------
# Orphan arm: baseline present, onlycode missing. The summary must still
# render the baseline row without crashing or inventing an onlycode row.
# ---------------------------------------------------------------------------


def test_orphan_arm_stdout_is_pinned():
    fixture_dir = FIXTURES_DIR / "orphan_arm"
    result = _run(fixture_dir)
    assert result.exit_code == 0, result.output

    expected = _load_golden("orphan_arm_stdout.golden.txt")
    assert result.output == expected


def test_orphan_arm_csv_is_pinned(tmp_path: Path):
    fixture_dir = FIXTURES_DIR / "orphan_arm"
    out_path = tmp_path / "summary.csv"
    result = _run(fixture_dir, out_path)
    assert result.exit_code == 0, result.output

    expected_csv = _render_csv_golden("orphan_arm.golden.csv", fixture_dir)
    actual = out_path.read_text()
    assert actual == expected_csv


# ---------------------------------------------------------------------------
# Sanity: the `--out` option also echoes a "CSV written to ..." trailer on
# stdout. Pinning this explicitly protects callers who parse the stream.
# ---------------------------------------------------------------------------


def test_csv_trailer_message_on_stdout(tmp_path: Path):
    fixture_dir = FIXTURES_DIR / "orphan_arm"
    out_path = tmp_path / "summary.csv"
    result = _run(fixture_dir, out_path)
    assert result.exit_code == 0
    assert result.output.endswith(f"\nCSV written to {out_path}\n")


# ---------------------------------------------------------------------------
# Edge: empty results dir emits the "No result files found" message and
# exits 0 (not 1). Pin this contract.
# ---------------------------------------------------------------------------


def test_empty_results_dir_is_noop(tmp_path: Path):
    result = _run(tmp_path)
    assert result.exit_code == 0
    assert result.output == f"No result files found in {tmp_path}/\n"


# ---------------------------------------------------------------------------
# Edge: --results-dir that does not exist exits 1 with a click usage error
# (type=Path(exists=True)). Pin the exit code so the contract is explicit.
# ---------------------------------------------------------------------------


def test_missing_results_dir_errors_out(tmp_path: Path):
    missing = tmp_path / "does-not-exist"
    runner = CliRunner()
    result = runner.invoke(
        analyze_command,
        ["summary", "--results-dir", str(missing)],
        catch_exceptions=False,
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Issue #108: artifact-mode layout detection and leak column.
# ---------------------------------------------------------------------------


def _write_artifact_result(
    results_dir: Path,
    iid: str,
    arm: str,
    run_idx: int,
    verdict: str,
    leak_detected: bool,
) -> None:
    import json as _json
    run_dir = results_dir / iid / arm / f"run{run_idx}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "result.json").write_text(_json.dumps({
        "instance_id": iid,
        "arm": arm,
        "run_idx": run_idx,
        "verdict": verdict,
        "leak_detected": leak_detected,
        "cost_usd": 0.01,
        "num_turns": 3,
        "wall_secs": 12,
        "grade_result": {"passed": verdict == "PASS", "score": 1.0, "detail": ""},
        "budget": {"max_code_runs": 0, "max_wall_seconds": 0, "enforcement": "OFF"},
        "claude_version": "claude-test",
        "agent_jsonl_path": str(run_dir / "agent.jsonl"),
    }))


def test_artifact_layout_shows_leak_column(tmp_path: Path):
    _write_artifact_result(tmp_path, "cat__slug_a", "code_only", 1, "PASS", False)
    _write_artifact_result(tmp_path, "cat__slug_b", "code_only", 1, "PASS", True)
    result = _run(tmp_path)
    assert result.exit_code == 0, result.output
    assert "leak" in result.output  # column header present
    # Tainted row marker (Y) and clean row marker (.)
    assert "Y" in result.output
    # Tainted-run counter is surfaced.
    assert "Tainted runs" in result.output
    # Clean pass-rate excludes the tainted row: 1 clean, 1 pass -> 100.0%
    assert "100.0%" in result.output


def test_artifact_layout_csv_contains_leak_column(tmp_path: Path):
    _write_artifact_result(tmp_path, "cat__slug_a", "code_only", 1, "PASS", False)
    _write_artifact_result(tmp_path, "cat__slug_b", "tool_rich", 1, "FAIL", True)
    out_csv = tmp_path / "out.csv"
    result = _run(tmp_path, out_csv)
    assert result.exit_code == 0, result.output
    csv_text = out_csv.read_text()
    assert "leak_detected" in csv_text.splitlines()[0]
    assert "True" in csv_text
    assert "False" in csv_text


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
