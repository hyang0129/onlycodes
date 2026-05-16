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
# env_fail (Issue #238) — verdict surfaces as its own row and is excluded
# from the per-arm pass-rate aggregate.
# ---------------------------------------------------------------------------


def test_env_fail_appears_in_table_and_excluded_from_pass_rate():
    fixture_dir = FIXTURES_DIR / "env_fail_arm"
    result = _run(fixture_dir)
    assert result.exit_code == 0, result.output
    # env_fail verdict shows up in the per-row table.
    assert "env_fail" in result.output
    # The aggregate footer is emitted and pass_rate is n/a (denominator excludes env_fail).
    assert "Per-arm aggregates" in result.output
    assert "env_fail=1" in result.output
    assert "denominator=0" in result.output
    assert "pass_rate=n/a" in result.output


# ---------------------------------------------------------------------------
# Issue #253 — Codex cost estimates: ~$ prefix and price-table lookup
# ---------------------------------------------------------------------------


def _write_codex_run_fixture(
    fixture_dir: Path,
    *,
    instance_id: str,
    arm: str,
    run_idx: int,
    model: str | None,
    verdict: str,
    input_tokens: int = 0,
    cached_input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    """Build a minimal Codex JSONL + _test.txt pair for a single arm/run."""
    import json as _json
    fixture_dir.mkdir(parents=True, exist_ok=True)
    jsonl = fixture_dir / f"{instance_id}_{arm}_run{run_idx}.jsonl"
    lines = []
    meta: dict = {
        "type": "meta",
        "instance_id": instance_id,
        "arm": arm,
        "run": run_idx,
        "agent_surface": "codex_cli",
    }
    if model is not None:
        meta["model"] = model
    lines.append(_json.dumps(meta))
    lines.append(_json.dumps({"type": "turn.started"}))
    if input_tokens or output_tokens:
        lines.append(_json.dumps({
            "type": "turn.completed",
            "usage": {
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_input_tokens,
                "output_tokens": output_tokens,
            },
        }))
    else:
        lines.append(_json.dumps({"type": "turn.completed"}))
    jsonl.write_text("\n".join(lines) + "\n")
    (fixture_dir / f"{instance_id}_{arm}_run{run_idx}_test.txt").write_text(
        f"{verdict}\n"
    )


def test_codex_cli_cost_displayed_with_tilde_prefix(tmp_path: Path):
    """``analyze summary`` prepends ``~`` to costs from codex_cli runs.

    Acceptance criterion for issue #253: the cost column for a codex_cli row
    must be visually distinguishable from a claude_code row to make clear it
    is an estimate (token-count × price table) rather than a billed figure.
    """
    _write_codex_run_fixture(
        tmp_path,
        instance_id="myrepo__test-1",
        arm="baseline",
        run_idx=1,
        model="gpt-5.5",
        verdict="PASS",
        input_tokens=10_000,
        cached_input_tokens=2_000,
        output_tokens=500,
    )
    result = _run(tmp_path)
    assert result.exit_code == 0, result.output
    # The dollar amount comes from CodexRunner.extract_metadata; we only assert
    # the marker prefix is present so the test does not break on minor price
    # rounding.
    assert "~$" in result.output, result.output


def test_codex_cli_unknown_model_shows_na(tmp_path: Path):
    """Unknown model → cost=None → 'N/A' in the table (no ~$ prefix)."""
    _write_codex_run_fixture(
        tmp_path,
        instance_id="myrepo__test-2",
        arm="baseline",
        run_idx=1,
        model="totally-fake-model-99",
        verdict="PASS",
        input_tokens=1000,
        output_tokens=100,
    )
    result = _run(tmp_path)
    assert result.exit_code == 0, result.output
    # Confirm the row exists and has N/A (no ~$).
    assert "totally-fake-model" not in result.output  # we don't print model
    assert "myrepo__test-2" in result.output
    assert "N/A" in result.output
    assert "~$" not in result.output


def test_codex_cli_missing_model_in_meta_shows_na(tmp_path: Path):
    """Meta line without a 'model' field → cost=None → 'N/A'."""
    _write_codex_run_fixture(
        tmp_path,
        instance_id="myrepo__test-3",
        arm="baseline",
        run_idx=1,
        model=None,  # no model key in meta
        verdict="PASS",
        input_tokens=1000,
        output_tokens=100,
    )
    result = _run(tmp_path)
    assert result.exit_code == 0, result.output
    assert "N/A" in result.output
    assert "~$" not in result.output


def test_summary_parses_agent_surface_from_meta(tmp_path: Path):
    """`_parse_results` populates ArmResult.agent_surface from the meta line."""
    from swebench.analyze.summary import _parse_results
    _write_codex_run_fixture(
        tmp_path,
        instance_id="myrepo__test-4",
        arm="baseline",
        run_idx=1,
        model="gpt-5.4",
        verdict="PASS",
        input_tokens=1000,
        output_tokens=100,
    )
    results = _parse_results(tmp_path)
    assert len(results) == 1
    assert results[0].agent_surface == "codex_cli"
    assert results[0].cost_usd is not None
    assert results[0].cost_usd > 0


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
