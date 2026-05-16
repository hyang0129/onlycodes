"""Component tests for the codex cost-estimate boundary introduced in PR #253.

Two boundaries are covered here:

1. summary._parse_results → runner.CodexRunner.extract_metadata
   ``_parse_results`` now dispatches to the real ``CodexRunner().extract_metadata``
   for any ``codex_cli`` row. Tests verify: (a) the model slug flows from the
   JSONL meta line through ``_parse_results`` into ``ArmResult.cost_usd`` via
   the real price-table lookup; (b) unknown model → ``cost_usd is None``; (c)
   missing model field → ``cost_usd is None``.

2. summary._format_cost → ArmResult.agent_surface (the ~$ prefix contract)
   ``_format_cost`` must emit ``~$`` for ``codex_cli`` rows and ``$`` for
   ``claude_code`` rows. Tests verify the prefix reflects the ``agent_surface``
   field populated by ``_parse_results`` from the meta line — exercising the
   full chain: JSONL file → _parse_results → ArmResult → _format_cost → string.

Both boundaries exercise two or more real modules co-operating. The only doubled
seam is the filesystem (synthetic JSONL + _test.txt fixtures written under
``tmp_path``). No subprocess, no network, no external binaries.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swebench.analyze.summary import _format_cost, _parse_results


# ---------------------------------------------------------------------------
# Shared test-fixture builder
# ---------------------------------------------------------------------------


def _write_run_fixture(
    fixture_dir: Path,
    *,
    instance_id: str,
    arm: str,
    run_idx: int,
    agent_surface: str,
    model: str | None = None,
    verdict: str = "PASS",
    usages: list[dict] | None = None,
) -> Path:
    """Write a minimal JSONL + _test.txt pair under fixture_dir.

    ``usages`` is a list of dicts; each produces a ``turn.completed`` line.
    When ``usages`` is empty or ``None``, only a bare ``turn.completed``
    (no usage block) is emitted — which yields ``cost_usd=None``.

    Returns the JSONL path.
    """
    fixture_dir.mkdir(parents=True, exist_ok=True)
    jsonl = fixture_dir / f"{instance_id}_{arm}_run{run_idx}.jsonl"
    lines: list[str] = []

    # First line must be the meta record
    meta: dict = {
        "type": "meta",
        "instance_id": instance_id,
        "arm": arm,
        "run": run_idx,
        "agent_surface": agent_surface,
    }
    if model is not None:
        meta["model"] = model
    lines.append(json.dumps(meta))

    # Turns
    if usages:
        for usage in usages:
            lines.append(json.dumps({"type": "turn.started"}))
            lines.append(json.dumps({"type": "turn.completed", "usage": usage}))
    else:
        lines.append(json.dumps({"type": "turn.started"}))
        lines.append(json.dumps({"type": "turn.completed"}))

    jsonl.write_text("\n".join(lines) + "\n")
    test_txt = fixture_dir / f"{instance_id}_{arm}_run{run_idx}_test.txt"
    test_txt.write_text(f"{verdict}\n")
    return jsonl


# ---------------------------------------------------------------------------
# Boundary 1a: _parse_results → CodexRunner.extract_metadata (known model)
# ---------------------------------------------------------------------------


@pytest.mark.component
class TestSummaryParseResultsCallsCodexExtractMetadata:
    """summary._parse_results must delegate cost extraction to the real
    CodexRunner.extract_metadata for codex_cli rows.

    These tests use real filesystem fixtures and real module co-operation:
    swebench/analyze/summary.py → swebench/runner.py::CodexRunner.extract_metadata
    → swebench/codex_prices.toml (loaded by the real _load_codex_prices helper).

    The only seam doubled is the directory of JSONL files (tmp_path).
    """

    def test_known_model_produces_nonzero_cost_via_real_extract_metadata(
        self, tmp_path: Path
    ):
        """codex_cli row with known model + usage tokens → ArmResult.cost_usd > 0.

        This fails if summary.py stops calling CodexRunner.extract_metadata
        (e.g. reverts to the old regex-only path) or if the price-table lookup
        is broken.
        """
        _write_run_fixture(
            tmp_path,
            instance_id="myrepo__test-km-1",
            arm="baseline",
            run_idx=1,
            agent_surface="codex_cli",
            model="gpt-5.5",
            verdict="PASS",
            usages=[
                {
                    "input_tokens": 10_000,
                    "cached_input_tokens": 2_000,
                    "output_tokens": 500,
                }
            ],
        )
        results = _parse_results(tmp_path)
        assert len(results) == 1, f"Expected 1 ArmResult, got {results}"
        r = results[0]
        assert r.agent_surface == "codex_cli"
        assert r.cost_usd is not None, (
            "cost_usd must be a float for a known model (gpt-5.5) with usage data; "
            "got None — _parse_results is not calling CodexRunner.extract_metadata correctly"
        )
        assert r.cost_usd > 0, f"cost_usd must be positive; got {r.cost_usd}"

    def test_cost_matches_price_table_formula(self, tmp_path: Path):
        """The cost reported by _parse_results must equal the formula applied
        to the price table entries loaded by the real _load_codex_prices().

        This is the cross-module contract: summary.py delegates to runner.py,
        and runner.py reads the real codex_prices.toml. Any drift between the
        formula and the table is caught here.

        gpt-5.4-mini prices: input=$0.75/M, cached_input=$0.075/M, output=$4.50/M
        """
        input_tokens = 8_000
        cached_tokens = 1_000
        output_tokens = 400

        _write_run_fixture(
            tmp_path,
            instance_id="myrepo__test-km-2",
            arm="baseline",
            run_idx=1,
            agent_surface="codex_cli",
            model="gpt-5.4-mini",
            verdict="PASS",
            usages=[
                {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached_tokens,
                    "output_tokens": output_tokens,
                }
            ],
        )

        # Compute expected cost using the published gpt-5.4-mini prices.
        # (These match codex_prices.toml — if the table changes, this test
        # must be updated in tandem, which is the desired coupling.)
        non_cached = input_tokens - cached_tokens
        expected_cost = (
            non_cached * 0.75 + cached_tokens * 0.075 + output_tokens * 4.50
        ) / 1_000_000.0

        results = _parse_results(tmp_path)
        assert len(results) == 1
        r = results[0]
        assert r.cost_usd == pytest.approx(expected_cost, rel=1e-9), (
            f"cost_usd={r.cost_usd} does not match expected={expected_cost}. "
            "Either the price table or the formula in CodexRunner.extract_metadata "
            "has drifted from the expected formula."
        )

    def test_multiple_turns_summed_by_real_extract_metadata(self, tmp_path: Path):
        """Multiple turn.completed events are summed by the real extract_metadata.

        This validates the cross-module contract at the multi-turn code path.
        gpt-5.4 prices: input=$2.50/M, cached=$0.25/M, output=$15.00/M
        """
        _write_run_fixture(
            tmp_path,
            instance_id="myrepo__test-km-3",
            arm="baseline",
            run_idx=1,
            agent_surface="codex_cli",
            model="gpt-5.4",
            verdict="PASS",
            usages=[
                {"input_tokens": 1_000, "cached_input_tokens": 0, "output_tokens": 100},
                {"input_tokens": 2_000, "cached_input_tokens": 500, "output_tokens": 200},
            ],
        )

        # Totals: input=3000, cached=500, output=300
        non_cached = 3_000 - 500
        expected_cost = (
            non_cached * 2.50 + 500 * 0.25 + 300 * 15.00
        ) / 1_000_000.0

        results = _parse_results(tmp_path)
        assert len(results) == 1
        r = results[0]
        assert r.cost_usd == pytest.approx(expected_cost, rel=1e-9), (
            f"Multi-turn cost mismatch: got {r.cost_usd}, expected {expected_cost}"
        )


# ---------------------------------------------------------------------------
# Boundary 1b: _parse_results → CodexRunner.extract_metadata (degraded paths)
# ---------------------------------------------------------------------------


@pytest.mark.component
class TestSummaryParseResultsCodexDegradedPaths:
    """_parse_results must degrade gracefully to cost_usd=None when the codex
    JSONL is missing the data needed for a price estimate.

    These tests confirm that the real CodexRunner.extract_metadata returns
    (None, ...) for these cases and that _parse_results faithfully propagates
    cost_usd=None into the ArmResult.
    """

    def test_unknown_model_yields_none_cost(self, tmp_path: Path):
        """A model slug not in codex_prices.toml → cost_usd=None.

        The cross-module contract: summary.py must not hard-code model names;
        it delegates to CodexRunner.extract_metadata which reads the table.
        """
        _write_run_fixture(
            tmp_path,
            instance_id="myrepo__test-deg-1",
            arm="baseline",
            run_idx=1,
            agent_surface="codex_cli",
            model="totally-fake-model-xyz-99",
            verdict="PASS",
            usages=[{"input_tokens": 1000, "output_tokens": 100}],
        )
        results = _parse_results(tmp_path)
        assert len(results) == 1
        r = results[0]
        assert r.cost_usd is None, (
            f"Expected cost_usd=None for an unknown model; got {r.cost_usd}. "
            "The price-table lookup in CodexRunner.extract_metadata must fall through "
            "to None for unlisted models."
        )
        # turns should still be extracted even when cost is unavailable
        assert r.num_turns is not None and r.num_turns >= 1, (
            "num_turns must be populated even when cost cannot be estimated"
        )

    def test_missing_model_field_in_meta_yields_none_cost(self, tmp_path: Path):
        """When the meta line has agent_surface='codex_cli' but no 'model' field,
        cost_usd must be None.

        The real _read_meta_model() in runner.py returns None when the meta line
        lacks a ``model`` key. summary.py must propagate this as cost_usd=None.
        """
        _write_run_fixture(
            tmp_path,
            instance_id="myrepo__test-deg-2",
            arm="baseline",
            run_idx=1,
            agent_surface="codex_cli",
            model=None,  # meta line will have no 'model' key
            verdict="PASS",
            usages=[{"input_tokens": 1000, "output_tokens": 100}],
        )
        results = _parse_results(tmp_path)
        assert len(results) == 1
        r = results[0]
        assert r.cost_usd is None, (
            "cost_usd must be None when the meta line lacks a 'model' field; "
            f"got {r.cost_usd}"
        )

    def test_no_usage_block_yields_none_cost(self, tmp_path: Path):
        """Known model but no turn.completed carries a usage dict → cost_usd=None."""
        _write_run_fixture(
            tmp_path,
            instance_id="myrepo__test-deg-3",
            arm="baseline",
            run_idx=1,
            agent_surface="codex_cli",
            model="gpt-5.5",
            verdict="PASS",
            usages=None,  # turn.completed with no usage block
        )
        results = _parse_results(tmp_path)
        assert len(results) == 1
        r = results[0]
        assert r.cost_usd is None, (
            "cost_usd must be None when turn.completed carries no usage block; "
            f"got {r.cost_usd}"
        )


# ---------------------------------------------------------------------------
# Boundary 2: _format_cost → ArmResult.agent_surface (~$ vs $ prefix)
# ---------------------------------------------------------------------------


@pytest.mark.component
class TestFormatCostTildePrefixFromParsedArmResult:
    """_format_cost must emit ~$ for codex_cli rows and $ for claude_code rows.

    The prefix decision depends on ``ArmResult.agent_surface``, which is
    populated by ``_parse_results`` from the JSONL meta line. These tests
    drive the full chain: JSONL file → _parse_results → ArmResult → _format_cost,
    asserting that the surface field flows correctly across the summary→models
    boundary.
    """

    def test_codex_cli_row_uses_tilde_dollar_prefix(self, tmp_path: Path):
        """The complete chain must produce ``~$`` for a codex_cli row.

        Failure here means the surface detection or prefix logic is broken:
        either _parse_results is not reading agent_surface from the meta line,
        or _format_cost is not checking ArmResult.agent_surface correctly.
        """
        _write_run_fixture(
            tmp_path,
            instance_id="myrepo__test-pfx-1",
            arm="baseline",
            run_idx=1,
            agent_surface="codex_cli",
            model="gpt-5.5",
            verdict="PASS",
            usages=[{"input_tokens": 10_000, "cached_input_tokens": 0, "output_tokens": 500}],
        )
        results = _parse_results(tmp_path)
        assert len(results) == 1
        r = results[0]
        formatted = _format_cost(r)
        assert formatted.startswith("~$"), (
            f"codex_cli cost must be formatted as '~$<amount>'; got {formatted!r}. "
            "The ~$ prefix signals 'estimate' to reviewers (issue #253 acceptance criteria)."
        )

    def test_claude_code_row_uses_plain_dollar_prefix(self, tmp_path: Path):
        """The complete chain must produce ``$`` (no tilde) for a claude_code row.

        claude_code rows report the authoritative billed cost from the agent's
        own stream-json output, so the tilde must NOT appear.
        """
        fixture_dir = tmp_path
        fixture_dir.mkdir(parents=True, exist_ok=True)
        instance_id = "myrepo__test-pfx-2"
        arm = "baseline"
        run_idx = 1
        jsonl = fixture_dir / f"{instance_id}_{arm}_run{run_idx}.jsonl"
        # claude_code JSONL has total_cost_usd in a result line, no turn.completed usage
        jsonl.write_text(
            json.dumps({
                "type": "meta",
                "instance_id": instance_id,
                "arm": arm,
                "run": run_idx,
                "agent_surface": "claude_code",
            }) + "\n"
            + json.dumps({
                "type": "result",
                "total_cost_usd": 0.1234,
                "num_turns": 5,
            }) + "\n"
        )
        (fixture_dir / f"{instance_id}_{arm}_run{run_idx}_test.txt").write_text("PASS\n")

        results = _parse_results(fixture_dir)
        assert len(results) == 1
        r = results[0]
        assert r.agent_surface == "claude_code", (
            f"Expected agent_surface='claude_code'; got {r.agent_surface!r}"
        )
        assert r.cost_usd == pytest.approx(0.1234, rel=1e-6), (
            f"Expected cost_usd~0.1234 for claude_code row; got {r.cost_usd}"
        )
        formatted = _format_cost(r)
        assert formatted.startswith("$") and not formatted.startswith("~$"), (
            f"claude_code cost must be formatted as '$<amount>' (no tilde); got {formatted!r}"
        )

    def test_codex_none_cost_formats_as_na(self, tmp_path: Path):
        """Unknown model → cost_usd=None → _format_cost must return 'N/A' (no ~$ prefix).

        This exercises the None-guard in _format_cost across the full pipeline.
        """
        _write_run_fixture(
            tmp_path,
            instance_id="myrepo__test-pfx-3",
            arm="baseline",
            run_idx=1,
            agent_surface="codex_cli",
            model="unknown-model-xyz",
            verdict="PASS",
            usages=[{"input_tokens": 1000, "output_tokens": 100}],
        )
        results = _parse_results(tmp_path)
        assert len(results) == 1
        r = results[0]
        assert r.cost_usd is None
        formatted = _format_cost(r)
        assert formatted == "N/A", (
            f"cost_usd=None must format as 'N/A'; got {formatted!r}. "
            "Neither '~$' nor '$' must appear for uncosted rows."
        )

    def test_codex_prefix_persists_across_multiple_rows(self, tmp_path: Path):
        """When both codex_cli and claude_code rows are in the same results dir,
        each must get the correct prefix independently.

        This guards the iteration contract: the surface routing inside _parse_results
        must not leak between rows (e.g. a mutable default carrying state).
        """
        # Codex row
        _write_run_fixture(
            tmp_path,
            instance_id="myrepo__alpha",
            arm="baseline",
            run_idx=1,
            agent_surface="codex_cli",
            model="gpt-5.5",
            verdict="PASS",
            usages=[{"input_tokens": 5_000, "cached_input_tokens": 0, "output_tokens": 200}],
        )
        # Claude row — write manually so we control total_cost_usd
        claude_jsonl = tmp_path / "myrepo__bravo_baseline_run1.jsonl"
        claude_jsonl.write_text(
            json.dumps({
                "type": "meta",
                "instance_id": "myrepo__bravo",
                "arm": "baseline",
                "run": 1,
                "agent_surface": "claude_code",
            }) + "\n"
            + json.dumps({"type": "result", "total_cost_usd": 0.05, "num_turns": 3}) + "\n"
        )
        (tmp_path / "myrepo__bravo_baseline_run1_test.txt").write_text("PASS\n")

        results = _parse_results(tmp_path)
        assert len(results) == 2, f"Expected 2 results; got {len(results)}"

        # Sort by instance_id for determinism
        by_id = {r.instance_id: r for r in results}
        codex_r = by_id["myrepo__alpha"]
        claude_r = by_id["myrepo__bravo"]

        assert codex_r.agent_surface == "codex_cli"
        assert claude_r.agent_surface == "claude_code"

        codex_fmt = _format_cost(codex_r)
        claude_fmt = _format_cost(claude_r)

        assert codex_fmt.startswith("~$"), (
            f"codex row must use ~$ prefix; got {codex_fmt!r}"
        )
        assert claude_fmt.startswith("$") and not claude_fmt.startswith("~$"), (
            f"claude_code row must use plain $ prefix; got {claude_fmt!r}"
        )
