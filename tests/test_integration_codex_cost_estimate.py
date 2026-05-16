"""Integration wiring tests for codex cost estimation — issue #253.

Scenario: slice-run-codex-model-flag-wiring
Scenario: slice-analyze-summary-codex-cli-tilde
Tier: wiring

These tests exercise the full CLI dispatch path through Click
(swebench/cli.py → swebench/run.py / swebench/analyze/summary.py)
without invoking a real codex binary or a real benchmark run.

What they verify (wiring only — no exact output comparison):

Scenario 1 — slice-run-codex-model-flag-wiring
  1. ``swebench run --help`` lists ``--codex-model`` in the option table.
  2. The ``--codex-model`` default is ``gpt-5.5`` (plan acceptance criterion).
  3. ``--codex-model`` is described in the help text so users can discover it.
  4. The flag is registered on the Click command object (structural wiring).

Scenario 2 — slice-analyze-summary-codex-cli-tilde
  5. ``swebench analyze summary --results-dir <dir>`` shows ``~$`` for codex_cli
     rows (estimate marker) — routed through the full cli → analyze → summary
     dispatch chain.
  6. ``swebench analyze summary`` shows plain ``$`` for claude_code rows (no
     tilde prefix — authoritative billing).
  7. ``swebench analyze summary`` shows ``N/A`` for codex_cli rows whose JSONL
     model field is unknown (graceful degradation).
  8. The two surfaces coexist in the same results directory without collision.

Integration boundary: swebench/cli.py → swebench/run.py (run_command, Click
@option decorator) and swebench/cli.py → swebench/analyze/summary.py
(summary_command via analyze_command).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from swebench.cli import cli
from swebench.run import run_command as _run_command


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_codex_run_dir(
    results_dir: Path,
    *,
    instance_id: str,
    arm: str,
    run_idx: int,
    model: str | None,
    verdict: str,
    input_tokens: int = 10_000,
    cached_input_tokens: int = 2_000,
    output_tokens: int = 500,
    agent_surface: str = "codex_cli",
) -> None:
    """Write synthetic codex result files into results_dir.

    Creates a JSONL meta line (with optional model field) + one
    turn.completed event + a test verdict file.  Mirrors the real file
    layout written by run.py so _parse_results() picks them up.
    """
    results_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{instance_id}_{arm}_run{run_idx}"

    meta: dict = {
        "type": "meta",
        "instance_id": instance_id,
        "arm": arm,
        "run": run_idx,
        "agent_surface": agent_surface,
        "agent_binary": "/usr/bin/codex",
        "agent_version": "test-1.0",
    }
    if model is not None:
        meta["model"] = model

    usage_line = {
        "type": "turn.completed",
        "usage": {
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "output_tokens": output_tokens,
        },
    }

    jsonl_path = results_dir / f"{stem}.jsonl"
    jsonl_path.write_text(
        json.dumps(meta) + "\n" + json.dumps(usage_line) + "\n"
    )

    test_path = results_dir / f"{stem}_test.txt"
    test_path.write_text(f"{verdict}\n")


def _make_claude_run_dir(
    results_dir: Path,
    *,
    instance_id: str,
    arm: str,
    run_idx: int,
    verdict: str,
    cost_usd: float,
    num_turns: int = 5,
) -> None:
    """Write synthetic claude_code result files into results_dir.

    Mirrors what ClaudeRunner.invoke writes (stream-json including the
    assistant-level result record) so _parse_results() can pick up the
    ``total_cost_usd`` field.
    """
    results_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{instance_id}_{arm}_run{run_idx}"

    meta: dict = {
        "type": "meta",
        "instance_id": instance_id,
        "arm": arm,
        "run": run_idx,
        "agent_surface": "claude_code",
        "agent_binary": "/usr/bin/claude",
    }
    result_line = {
        "type": "result",
        "total_cost_usd": cost_usd,
        "num_turns": num_turns,
    }

    jsonl_path = results_dir / f"{stem}.jsonl"
    jsonl_path.write_text(
        json.dumps(meta) + "\n" + json.dumps(result_line) + "\n"
    )

    test_path = results_dir / f"{stem}_test.txt"
    test_path.write_text(f"{verdict}\n")


@pytest.fixture
def runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# Scenario 1: slice-run-codex-model-flag-wiring
#
# swebench run --help must expose --codex-model with its default (gpt-5.5).
# ---------------------------------------------------------------------------


def test_run_help_lists_codex_model_option(runner):
    """``swebench run --help`` must list ``--codex-model`` in the option table.

    Wiring assertion: the flag must be registered on run_command and rendered
    in the Click help output visible to users and operators.
    """
    result = runner.invoke(cli, ["run", "--help"])

    assert result.exit_code == 0, (
        f"``swebench run --help`` must exit 0; got {result.exit_code}.\n{result.output}"
    )
    assert "--codex-model" in result.output, (
        f"``--codex-model`` not found in ``swebench run --help`` output:\n{result.output}"
    )


def test_run_codex_model_default_is_gpt55(runner):
    """``--codex-model`` default must be ``gpt-5.5`` (plan acceptance criterion).

    Schema assertion: Click renders the default in the help text.  The issue
    acceptance criteria specify gpt-5.5 as the reproducible default.
    """
    result = runner.invoke(cli, ["run", "--help"])

    assert result.exit_code == 0, (
        f"Expected exit 0, got {result.exit_code}:\n{result.output}"
    )
    # The default must appear in the section near --codex-model.
    codex_model_idx = result.output.find("--codex-model")
    assert codex_model_idx != -1, "--codex-model not in help"

    # Extract the block after --codex-model (up to next option or end).
    block = result.output[codex_model_idx:codex_model_idx + 400]
    assert "gpt-5.5" in block, (
        f"Default 'gpt-5.5' not shown near --codex-model in help block:\n{block!r}"
    )


def test_run_codex_model_registered_on_click_command():
    """``--codex-model`` must be a registered Click parameter on run_command.

    Structural wiring: validates that the @click.option decorator is in place,
    independently of the rendered help text.
    """
    param_names = [p.name for p in _run_command.params]
    assert "codex_model" in param_names, (
        f"codex_model parameter not registered on run_command; "
        f"registered params: {param_names}"
    )


def test_run_codex_model_param_default():
    """The Click Parameter for --codex-model must have default='gpt-5.5'."""
    param = next(
        (p for p in _run_command.params if p.name == "codex_model"), None
    )
    assert param is not None, "codex_model param not found on run_command"
    assert param.default == "gpt-5.5", (
        f"Expected default='gpt-5.5', got {param.default!r}"
    )


def test_run_codex_model_option_is_text_type():
    """``--codex-model`` must accept free-form text (not a constrained Choice).

    Schema assertion: users should be able to specify any model slug, including
    future models not yet in the price table.  Unknown models degrade to
    cost=None rather than being rejected at parse time.
    """
    import click as _click

    param = next(
        (p for p in _run_command.params if p.name == "codex_model"), None
    )
    assert param is not None, "codex_model param not found"
    # STRING type means any text is accepted.
    assert param.type in (
        _click.STRING,
        _click.types.StringParamType(),
        str,
    ) or str(param.type) in ("STRING", "TEXT", "<class 'str'>"), (
        f"Expected STRING type for --codex-model; got {param.type!r}"
    )


# ---------------------------------------------------------------------------
# Scenario 2: slice-analyze-summary-codex-cli-tilde
#
# swebench analyze summary must show ~$ for codex_cli rows and plain $ for
# claude_code rows, routed through the full cli → analyze → summary chain.
# ---------------------------------------------------------------------------


def test_analyze_summary_shows_tilde_prefix_for_codex_cli(tmp_path, monkeypatch):
    """``swebench analyze summary`` must show ``~$`` for codex_cli runs.

    Integration wiring assertion: the cost formatter (_format_cost) must be
    connected to the summary_command output path through the full CLI dispatch
    chain (cli → analyze_command → summary_command → _parse_results →
    _format_cost → click.echo).

    The ``~`` marker signals that the figure is a price-table estimate, not a
    billed amount.  Verifying this through the CLI (not just the unit
    _format_cost function) ensures the wiring from parse → format → output is
    intact.
    """
    monkeypatch.setattr("swebench.analyze.summary.repo_root", lambda: tmp_path)
    results_dir = tmp_path / "runs" / "swebench"

    _make_codex_run_dir(
        results_dir,
        instance_id="myrepo__issue-1",
        arm="baseline",
        run_idx=1,
        model="gpt-5.5",
        verdict="PASS",
        input_tokens=10_000,
        cached_input_tokens=2_000,
        output_tokens=500,
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["analyze", "summary", "--results-dir", str(results_dir)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, (
        f"analyze summary must exit 0; got {result.exit_code}.\n{result.output}"
    )
    assert "~$" in result.output, (
        f"Expected '~$' cost prefix for codex_cli row in summary output.\n"
        f"Output:\n{result.output}"
    )


def test_analyze_summary_plain_dollar_for_claude_code(tmp_path, monkeypatch):
    """``swebench analyze summary`` must show plain ``$`` for claude_code runs.

    Complementary schema assertion: authoritative USD billed by Claude must NOT
    get the ``~`` estimate marker.  The two surfaces must be visually
    distinguishable.
    """
    monkeypatch.setattr("swebench.analyze.summary.repo_root", lambda: tmp_path)
    results_dir = tmp_path / "runs" / "swebench"

    _make_claude_run_dir(
        results_dir,
        instance_id="myrepo__claude-1",
        arm="baseline",
        run_idx=1,
        verdict="PASS",
        cost_usd=0.4567,
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["analyze", "summary", "--results-dir", str(results_dir)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, (
        f"analyze summary must exit 0; got {result.exit_code}.\n{result.output}"
    )
    # Plain $ must appear (the cost is not zero).
    assert "$" in result.output, (
        f"Expected '$' in summary output for claude_code row.\n{result.output}"
    )
    # The tilde prefix must NOT appear for claude rows.
    assert "~$" not in result.output, (
        f"claude_code rows must NOT use '~$' prefix; got:\n{result.output}"
    )


def test_analyze_summary_na_for_unknown_codex_model(tmp_path, monkeypatch):
    """Unknown codex model → cost=None → ``N/A`` in summary (no ``~$``).

    Graceful degradation: if the model slug is not in codex_prices.toml,
    the CLI must emit N/A rather than crashing or showing a wrong value.
    The route from extract_metadata → _parse_results → _format_cost must
    handle this cleanly through the full CLI dispatch chain.
    """
    monkeypatch.setattr("swebench.analyze.summary.repo_root", lambda: tmp_path)
    results_dir = tmp_path / "runs" / "swebench"

    _make_codex_run_dir(
        results_dir,
        instance_id="myrepo__issue-2",
        arm="onlycode",
        run_idx=1,
        model="totally-unknown-model-99",
        verdict="FAIL",
        input_tokens=5_000,
        output_tokens=300,
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["analyze", "summary", "--results-dir", str(results_dir)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, (
        f"analyze summary must exit 0; got {result.exit_code}.\n{result.output}"
    )
    assert "N/A" in result.output, (
        f"Expected 'N/A' for unknown model cost.\n{result.output}"
    )
    assert "~$" not in result.output, (
        f"'~$' must not appear when cost is N/A.\n{result.output}"
    )


def test_analyze_summary_mixed_surfaces_in_same_dir(tmp_path, monkeypatch):
    """codex_cli and claude_code results coexist correctly in one results dir.

    Integration contract: ``_parse_results`` uses the ``agent_surface`` meta
    field to route each row to the right cost parser.  Both surfaces must
    appear correctly in the same table — ``~$`` for codex, ``$`` for claude —
    without either row interfering with the other.
    """
    monkeypatch.setattr("swebench.analyze.summary.repo_root", lambda: tmp_path)
    results_dir = tmp_path / "runs" / "swebench"

    # codex_cli row — should show ~$
    _make_codex_run_dir(
        results_dir,
        instance_id="myrepo__codex-1",
        arm="baseline",
        run_idx=1,
        model="gpt-5.4",
        verdict="PASS",
        input_tokens=8_000,
        cached_input_tokens=1_000,
        output_tokens=400,
    )

    # claude_code row — should show plain $
    _make_claude_run_dir(
        results_dir,
        instance_id="myrepo__claude-1",
        arm="baseline",
        run_idx=1,
        verdict="PASS",
        cost_usd=0.3456,
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["analyze", "summary", "--results-dir", str(results_dir)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, (
        f"analyze summary must exit 0; got {result.exit_code}.\n{result.output}"
    )
    # Both rows must appear.
    assert "myrepo__codex-1" in result.output, (
        f"codex row not found in output:\n{result.output}"
    )
    assert "myrepo__claude-1" in result.output, (
        f"claude row not found in output:\n{result.output}"
    )
    # Estimate marker must be present (for the codex row).
    assert "~$" in result.output, (
        f"Expected '~$' for codex_cli row in mixed-surface summary.\n{result.output}"
    )
    # Plain dollar must be present (for the claude row).
    assert "$" in result.output, (
        f"Expected '$' for claude_code row in mixed-surface summary.\n{result.output}"
    )


def test_analyze_summary_codex_na_when_meta_has_no_model(tmp_path, monkeypatch):
    """codex_cli row with no ``model`` field in meta → ``N/A`` (not a crash).

    Defensive degradation: old result files written before issue #253 may not
    have the model field.  ``swebench analyze summary`` must still render the
    row as N/A without raising an exception or emitting invalid output.
    """
    monkeypatch.setattr("swebench.analyze.summary.repo_root", lambda: tmp_path)
    results_dir = tmp_path / "runs" / "swebench"

    _make_codex_run_dir(
        results_dir,
        instance_id="myrepo__issue-3",
        arm="baseline",
        run_idx=1,
        model=None,   # no model key in meta line
        verdict="FAIL",
        input_tokens=1_000,
        output_tokens=100,
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["analyze", "summary", "--results-dir", str(results_dir)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, (
        f"analyze summary must exit 0 even without model field; "
        f"got {result.exit_code}.\n{result.output}"
    )
    assert "N/A" in result.output, (
        f"Expected 'N/A' when model field is absent.\n{result.output}"
    )
    assert "~$" not in result.output, (
        f"'~$' must not appear when model is absent (cost is N/A).\n{result.output}"
    )
