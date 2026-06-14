"""Integration tests for scripts/power_analysis.py — wiring tier.

Scenario: slice-power-analysis-cli
Tier: wiring

Exercises the full vertical slice of the power-analysis CLI:

  - Subprocess boundary: ``python scripts/power_analysis.py --runs <dir> ...``
    exits 0, produces the two artifact files, and prints expected output.
  - Argument parsing wiring: ``--help`` resolves, required ``--runs`` flag is
    enforced, missing run-dir is rejected.
  - Run-directory discovery: the CLI discovers and reads JSONL + _test.txt
    files from the supplied run directories without crashing.
  - Output file creation: both ``<prefix>.json`` and ``<prefix>.csv`` are
    created and parseable (schema structure, not exact values).

These tests exercise the subprocess / argparse boundary — a layer the unit
tests in ``test_power_analysis.py`` do not cover (those call ``pa.main([...])``
in-process). The integration tier catches wiring breaks such as incorrect
import paths, argparse mis-registration, or output-directory creation failures.

Per-test budget: each test completes in well under 60 s. No network, no
Docker, no external services — all fixtures are synthetic tmp_path trees.

Run with:
    pytest tests/test_integration_power_analysis_wiring.py -v -m integration
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers shared with the artifact tier (inline to keep files independent)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "power_analysis.py"
PYTHON = sys.executable


def _write_claude_jsonl(
    path: Path,
    *,
    instance: str,
    arm: str,
    cost: float,
    first_call_cache_read: int = 100,
) -> None:
    """Write a minimal CLAUDE-format JSONL that power_analysis.py can parse."""
    input_tokens = 500
    lines = [
        json.dumps({"type": "meta", "instance_id": instance, "arm": arm,
                    "agent_surface": "claude_code"}),
        json.dumps({"type": "assistant", "message": {
            "id": f"msg_{instance}_{arm}",
            "model": "claude-sonnet-4-6",
            "usage": {
                "input_tokens": input_tokens,
                "cache_read_input_tokens": first_call_cache_read,
                "cache_creation_input_tokens": 50,
                "output_tokens": 20,
            }}}),
        json.dumps({"type": "result", "total_cost_usd": cost, "num_turns": 3,
                    "usage": {"input_tokens": input_tokens, "output_tokens": 20}}),
    ]
    path.write_text("\n".join(lines) + "\n")


def _make_run_dir(
    run_dir: Path,
    *,
    instances: list[str],
    treatment_cost: float = 1.2,
    reference_cost: float = 1.0,
    treatment_arm: str = "onlycode",
    reference_arm: str = "baseline",
) -> None:
    """Write a minimal SWE-bench run-dir with two arms per instance."""
    run_dir.mkdir(parents=True, exist_ok=True)
    for iid in instances:
        stem_t = f"{iid}_{treatment_arm}_run1"
        stem_r = f"{iid}_{reference_arm}_run1"
        _write_claude_jsonl(
            run_dir / f"{stem_t}.jsonl",
            instance=iid, arm=treatment_arm, cost=treatment_cost,
        )
        (run_dir / f"{stem_t}_test.txt").write_text("ran tests\nPASS\n")
        _write_claude_jsonl(
            run_dir / f"{stem_r}.jsonl",
            instance=iid, arm=reference_arm, cost=reference_cost,
        )
        (run_dir / f"{stem_r}_test.txt").write_text("ran tests\nPASS\n")


def _minimal_instances(n: int = 10) -> list[str]:
    """Generate n instance IDs spread across two repos for stratification."""
    repos = ["django", "sklearn"]
    return [f"{repos[i % len(repos)]}__issue-{i:04d}" for i in range(n)]


def _run_cli(args: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess:
    """Invoke the power_analysis CLI as a subprocess using the repo venv Python."""
    return subprocess.run(
        [PYTHON, str(SCRIPT)] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# 1 — CLI Schema Wiring
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_help_exits_zero():
    """``power_analysis.py --help`` must exit 0 and show usage."""
    result = _run_cli(["--help"])
    assert result.returncode == 0, result.stderr
    assert "usage" in result.stdout.lower() or "Usage" in result.stdout


@pytest.mark.integration
def test_help_documents_runs_flag():
    """``--runs`` must appear in --help output (it is the only required argument)."""
    result = _run_cli(["--help"])
    assert result.returncode == 0, result.stderr
    assert "--runs" in result.stdout


@pytest.mark.integration
def test_help_documents_out_prefix():
    """``--out-prefix`` must appear in --help (output path is configurable)."""
    result = _run_cli(["--help"])
    assert result.returncode == 0, result.stderr
    assert "--out-prefix" in result.stdout


@pytest.mark.integration
def test_help_documents_treatment_and_reference_flags():
    """``--treatment`` and ``--reference`` flags must be advertised in --help."""
    result = _run_cli(["--help"])
    assert result.returncode == 0, result.stderr
    assert "--treatment" in result.stdout
    assert "--reference" in result.stdout


@pytest.mark.integration
def test_missing_runs_flag_fails():
    """Invoking without ``--runs`` must exit non-zero (required argument)."""
    result = _run_cli([])
    assert result.returncode != 0


@pytest.mark.integration
def test_nonexistent_run_dir_fails(tmp_path: Path):
    """``--runs`` pointing to a non-existent directory must exit non-zero."""
    missing = tmp_path / "no_such_dir"
    out_prefix = str(tmp_path / "out" / "ws-a")
    result = _run_cli(["--runs", str(missing), "--out-prefix", out_prefix,
                       "--n-boot", "100", "--power-sims", "20",
                       "--n-min", "5", "--n-max", "5", "--n-step", "5"])
    assert result.returncode != 0


# ---------------------------------------------------------------------------
# 2 — Run-directory discovery and basic output creation
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cli_exits_zero_on_valid_run_dir(tmp_path: Path):
    """CLI exits 0 when given a valid synthetic run directory."""
    run_dir = tmp_path / "full_run_seed_1"
    _make_run_dir(run_dir, instances=_minimal_instances(8))
    out_prefix = str(tmp_path / "out" / "ws-a")

    result = _run_cli([
        "--runs", str(run_dir),
        "--n-boot", "100",
        "--power-sims", "20",
        "--n-min", "5",
        "--n-max", "5",
        "--n-step", "5",
        "--seed", "0",
        "--out-prefix", out_prefix,
    ])
    assert result.returncode == 0, result.stderr


@pytest.mark.integration
def test_cli_creates_json_output(tmp_path: Path):
    """CLI creates ``<prefix>.json`` output file."""
    run_dir = tmp_path / "full_run_seed_1"
    _make_run_dir(run_dir, instances=_minimal_instances(8))
    out_prefix = str(tmp_path / "out" / "ws-a")

    _run_cli([
        "--runs", str(run_dir),
        "--n-boot", "100",
        "--power-sims", "20",
        "--n-min", "5",
        "--n-max", "5",
        "--n-step", "5",
        "--seed", "0",
        "--out-prefix", out_prefix,
    ])
    assert (tmp_path / "out" / "ws-a.json").exists()


@pytest.mark.integration
def test_cli_creates_csv_output(tmp_path: Path):
    """CLI creates ``<prefix>.csv`` output file."""
    run_dir = tmp_path / "full_run_seed_1"
    _make_run_dir(run_dir, instances=_minimal_instances(8))
    out_prefix = str(tmp_path / "out" / "ws-a")

    _run_cli([
        "--runs", str(run_dir),
        "--n-boot", "100",
        "--power-sims", "20",
        "--n-min", "5",
        "--n-max", "5",
        "--n-step", "5",
        "--seed", "0",
        "--out-prefix", out_prefix,
    ])
    assert (tmp_path / "out" / "ws-a.csv").exists()


@pytest.mark.integration
def test_cli_stdout_contains_calibration_gate(tmp_path: Path):
    """CLI stdout must include ``Calibration gate`` header from _print_report."""
    run_dir = tmp_path / "full_run_seed_1"
    _make_run_dir(run_dir, instances=_minimal_instances(8))
    out_prefix = str(tmp_path / "out" / "ws-a")

    result = _run_cli([
        "--runs", str(run_dir),
        "--n-boot", "100",
        "--power-sims", "20",
        "--n-min", "5",
        "--n-max", "5",
        "--n-step", "5",
        "--seed", "0",
        "--out-prefix", out_prefix,
    ])
    assert result.returncode == 0, result.stderr
    assert "Calibration gate" in result.stdout


@pytest.mark.integration
def test_cli_stdout_contains_power_curve_section(tmp_path: Path):
    """CLI stdout must include the power curve section header."""
    run_dir = tmp_path / "full_run_seed_1"
    _make_run_dir(run_dir, instances=_minimal_instances(8))
    out_prefix = str(tmp_path / "out" / "ws-a")

    result = _run_cli([
        "--runs", str(run_dir),
        "--n-boot", "100",
        "--power-sims", "20",
        "--n-min", "5",
        "--n-max", "5",
        "--n-step", "5",
        "--seed", "0",
        "--out-prefix", out_prefix,
    ])
    assert result.returncode == 0, result.stderr
    assert "Power curve" in result.stdout


@pytest.mark.integration
def test_cli_stdout_contains_gonogo_section(tmp_path: Path):
    """CLI stdout must include the Go/no-go section header."""
    run_dir = tmp_path / "full_run_seed_1"
    _make_run_dir(run_dir, instances=_minimal_instances(8))
    out_prefix = str(tmp_path / "out" / "ws-a")

    result = _run_cli([
        "--runs", str(run_dir),
        "--n-boot", "100",
        "--power-sims", "20",
        "--n-min", "5",
        "--n-max", "5",
        "--n-step", "5",
        "--seed", "0",
        "--out-prefix", out_prefix,
    ])
    assert result.returncode == 0, result.stderr
    assert "Go/no-go" in result.stdout or "go/no-go" in result.stdout.lower()


# ---------------------------------------------------------------------------
# 3 — JSON output schema structure (no exact values)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_json_output_is_valid_json(tmp_path: Path):
    """JSON output file must be valid JSON."""
    run_dir = tmp_path / "full_run_seed_1"
    _make_run_dir(run_dir, instances=_minimal_instances(8))
    out_prefix = str(tmp_path / "out" / "ws-a")

    _run_cli([
        "--runs", str(run_dir),
        "--n-boot", "100",
        "--power-sims", "20",
        "--n-min", "5",
        "--n-max", "5",
        "--n-step", "5",
        "--seed", "0",
        "--out-prefix", out_prefix,
    ])
    data = json.loads((tmp_path / "out" / "ws-a.json").read_text())
    assert isinstance(data, dict)


@pytest.mark.integration
def test_json_output_has_required_top_level_keys(tmp_path: Path):
    """JSON output must contain calibration, log_scale_effect, power_analysis, go_nogo."""
    run_dir = tmp_path / "full_run_seed_1"
    _make_run_dir(run_dir, instances=_minimal_instances(8))
    out_prefix = str(tmp_path / "out" / "ws-a")

    _run_cli([
        "--runs", str(run_dir),
        "--n-boot", "100",
        "--power-sims", "20",
        "--n-min", "5",
        "--n-max", "5",
        "--n-step", "5",
        "--seed", "0",
        "--out-prefix", out_prefix,
    ])
    data = json.loads((tmp_path / "out" / "ws-a.json").read_text())
    assert "calibration" in data
    assert "log_scale_effect" in data
    assert "power_analysis" in data
    assert "go_nogo" in data


@pytest.mark.integration
def test_json_output_n_paired_is_integer(tmp_path: Path):
    """``n_paired`` in JSON output must be a positive integer."""
    run_dir = tmp_path / "full_run_seed_1"
    _make_run_dir(run_dir, instances=_minimal_instances(8))
    out_prefix = str(tmp_path / "out" / "ws-a")

    _run_cli([
        "--runs", str(run_dir),
        "--n-boot", "100",
        "--power-sims", "20",
        "--n-min", "5",
        "--n-max", "5",
        "--n-step", "5",
        "--seed", "0",
        "--out-prefix", out_prefix,
    ])
    data = json.loads((tmp_path / "out" / "ws-a.json").read_text())
    assert isinstance(data.get("n_paired"), int)
    assert data["n_paired"] > 0


@pytest.mark.integration
def test_json_output_gonogo_verdict_is_valid(tmp_path: Path):
    """``go_nogo.verdict`` must be one of the three documented values."""
    run_dir = tmp_path / "full_run_seed_1"
    _make_run_dir(run_dir, instances=_minimal_instances(8))
    out_prefix = str(tmp_path / "out" / "ws-a")

    _run_cli([
        "--runs", str(run_dir),
        "--n-boot", "100",
        "--power-sims", "20",
        "--n-min", "5",
        "--n-max", "5",
        "--n-step", "5",
        "--seed", "0",
        "--out-prefix", out_prefix,
    ])
    data = json.loads((tmp_path / "out" / "ws-a.json").read_text())
    assert data["go_nogo"]["verdict"] in ("powered_subset", "full_pool", "null_branch")


# ---------------------------------------------------------------------------
# 4 — CSV output schema structure
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_csv_output_has_required_columns(tmp_path: Path):
    """CSV must have columns: n, power_bootstrap, power_wilcoxon."""
    run_dir = tmp_path / "full_run_seed_1"
    _make_run_dir(run_dir, instances=_minimal_instances(8))
    out_prefix = str(tmp_path / "out" / "ws-a")

    _run_cli([
        "--runs", str(run_dir),
        "--n-boot", "100",
        "--power-sims", "20",
        "--n-min", "5",
        "--n-max", "5",
        "--n-step", "5",
        "--seed", "0",
        "--out-prefix", out_prefix,
    ])
    csv_path = tmp_path / "out" / "ws-a.csv"
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
    assert fieldnames is not None
    assert "n" in fieldnames
    assert "power_bootstrap" in fieldnames
    assert "power_wilcoxon" in fieldnames


@pytest.mark.integration
def test_csv_output_has_at_least_one_row(tmp_path: Path):
    """CSV must contain at least one data row."""
    run_dir = tmp_path / "full_run_seed_1"
    _make_run_dir(run_dir, instances=_minimal_instances(8))
    out_prefix = str(tmp_path / "out" / "ws-a")

    _run_cli([
        "--runs", str(run_dir),
        "--n-boot", "100",
        "--power-sims", "20",
        "--n-min", "5",
        "--n-max", "5",
        "--n-step", "5",
        "--seed", "0",
        "--out-prefix", out_prefix,
    ])
    csv_path = tmp_path / "out" / "ws-a.csv"
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 1


@pytest.mark.integration
def test_csv_n_column_is_numeric(tmp_path: Path):
    """CSV ``n`` column must be parseable as int in every row."""
    run_dir = tmp_path / "full_run_seed_1"
    _make_run_dir(run_dir, instances=_minimal_instances(8))
    out_prefix = str(tmp_path / "out" / "ws-a")

    _run_cli([
        "--runs", str(run_dir),
        "--n-boot", "100",
        "--power-sims", "20",
        "--n-min", "5",
        "--n-max", "10",
        "--n-step", "5",
        "--seed", "0",
        "--out-prefix", out_prefix,
    ])
    csv_path = tmp_path / "out" / "ws-a.csv"
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        int(row["n"])  # must not raise


@pytest.mark.integration
def test_csv_power_columns_are_floats(tmp_path: Path):
    """CSV power columns must be parseable as float in every row."""
    run_dir = tmp_path / "full_run_seed_1"
    _make_run_dir(run_dir, instances=_minimal_instances(8))
    out_prefix = str(tmp_path / "out" / "ws-a")

    _run_cli([
        "--runs", str(run_dir),
        "--n-boot", "100",
        "--power-sims", "20",
        "--n-min", "5",
        "--n-max", "5",
        "--n-step", "5",
        "--seed", "0",
        "--out-prefix", out_prefix,
    ])
    csv_path = tmp_path / "out" / "ws-a.csv"
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        float(row["power_bootstrap"])  # must not raise
        float(row["power_wilcoxon"])  # must not raise


# ---------------------------------------------------------------------------
# 5 — Multi-seed run-directory discovery
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cli_accepts_multiple_run_dirs(tmp_path: Path):
    """CLI must accept and combine multiple --runs arguments."""
    instances = _minimal_instances(8)
    d1 = tmp_path / "full_run_seed_1"
    d2 = tmp_path / "full_run_seed_2"
    _make_run_dir(d1, instances=instances)
    _make_run_dir(d2, instances=instances)
    out_prefix = str(tmp_path / "out" / "ws-a")

    result = _run_cli([
        "--runs", str(d1), str(d2),
        "--n-boot", "100",
        "--power-sims", "20",
        "--n-min", "5",
        "--n-max", "5",
        "--n-step", "5",
        "--seed", "0",
        "--out-prefix", out_prefix,
    ])
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "out" / "ws-a.json").exists()


@pytest.mark.integration
def test_cli_creates_output_parent_dirs(tmp_path: Path):
    """CLI must create the output parent directory hierarchy if it does not exist."""
    run_dir = tmp_path / "full_run_seed_1"
    _make_run_dir(run_dir, instances=_minimal_instances(6))
    # Deeply nested output path that does not yet exist
    out_prefix = str(tmp_path / "deep" / "nested" / "dir" / "ws-a")

    result = _run_cli([
        "--runs", str(run_dir),
        "--n-boot", "100",
        "--power-sims", "20",
        "--n-min", "5",
        "--n-max", "5",
        "--n-step", "5",
        "--seed", "0",
        "--out-prefix", out_prefix,
    ])
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "deep" / "nested" / "dir" / "ws-a.json").exists()
    assert (tmp_path / "deep" / "nested" / "dir" / "ws-a.csv").exists()
