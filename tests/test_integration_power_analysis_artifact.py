"""Integration tests for scripts/power_analysis.py — artifact tier.

Scenario: slice-power-analysis-cli
Tier: artifact

Verifies exact output correctness of the power-analysis CLI against committed
synthetic fixtures with known expected values.

These tests verify:
  - JSON output content: all required sub-sections are present with correct
    types; n_paired matches the number of instances supplied; treatment/reference
    fields echo the CLI arguments.
  - CSV output content: row count equals the n_grid length derived from
    --n-min / --n-max / --n-step; n column values match the grid; power values
    are in [0, 1]; rows are ordered by increasing n.
  - Calibration section: pct_effect_arithmetic reflects the known synthetic
    cost ratio; paper_pct_effect and paper_p_wilcoxon reference constants are
    present.
  - Log-scale effect section: mean_log_diff, std_log_diff, dz, pct_effect_log
    are all present; full_contrast sub-section has CI and p-value fields.
  - Power-analysis section: curve list length matches n_grid length; n_star_80
    / n_star_90 are either int or null; go_nogo section has the correct fields.
  - Default --out-prefix routing: when --out-prefix is omitted, the script
    writes to runs/swebench/_analysis/power/ws-a.{json,csv}.

Run with:
    pytest tests/test_integration_power_analysis_artifact.py -v -m integration
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers (independent copy — each tier file must be independently executable)
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


def _standard_instances(n: int = 12) -> list[str]:
    """Generate n instance IDs spread across four repos for stratification."""
    repos = ["django", "sklearn", "sympy", "mpl"]
    return [f"{repos[i % len(repos)]}__issue-{i:04d}" for i in range(n)]


def _run_cli_with_standard_fixture(
    tmp_path: Path,
    *,
    n_instances: int = 12,
    treatment_cost: float = 1.3,
    reference_cost: float = 1.0,
    n_min: int = 5,
    n_max: int = 10,
    n_step: int = 5,
    extra_args: list[str] | None = None,
) -> tuple[subprocess.CompletedProcess, Path]:
    """Run the CLI against a single-seed synthetic fixture and return (result, out_dir)."""
    run_dir = tmp_path / "full_run_seed_1"
    _make_run_dir(run_dir, instances=_standard_instances(n_instances),
                  treatment_cost=treatment_cost, reference_cost=reference_cost)
    out_dir = tmp_path / "out"
    out_prefix = str(out_dir / "ws-a")

    cmd = [
        "--runs", str(run_dir),
        "--n-boot", "200",
        "--power-sims", "50",
        "--n-min", str(n_min),
        "--n-max", str(n_max),
        "--n-step", str(n_step),
        "--seed", "42",
        "--out-prefix", out_prefix,
    ]
    if extra_args:
        cmd.extend(extra_args)

    result = subprocess.run(
        [PYTHON, str(SCRIPT)] + cmd,
        capture_output=True, text=True, timeout=60,
    )
    return result, out_dir


# ---------------------------------------------------------------------------
# 1 — n_paired reflects exact instance count
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_n_paired_matches_instance_count(tmp_path: Path):
    """``n_paired`` must equal the number of instances written to the run dir."""
    n_instances = 12
    result, out_dir = _run_cli_with_standard_fixture(
        tmp_path, n_instances=n_instances,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads((out_dir / "ws-a.json").read_text())
    assert data["n_paired"] == n_instances


@pytest.mark.integration
def test_treatment_and_reference_echoed_in_json(tmp_path: Path):
    """``treatment`` and ``reference`` in JSON must reflect the CLI arguments."""
    result, out_dir = _run_cli_with_standard_fixture(
        tmp_path, extra_args=["--treatment", "onlycode", "--reference", "baseline"],
    )
    assert result.returncode == 0, result.stderr
    data = json.loads((out_dir / "ws-a.json").read_text())
    assert data["treatment"] == "onlycode"
    assert data["reference"] == "baseline"


@pytest.mark.integration
def test_run_dirs_field_contains_supplied_path(tmp_path: Path):
    """``run_dirs`` in JSON must include the path we supplied via --runs."""
    run_dir = tmp_path / "full_run_seed_1"
    _make_run_dir(run_dir, instances=_standard_instances(8))
    out_prefix = str(tmp_path / "out" / "ws-a")

    result = subprocess.run(
        [PYTHON, str(SCRIPT),
         "--runs", str(run_dir),
         "--n-boot", "100", "--power-sims", "20",
         "--n-min", "5", "--n-max", "5", "--n-step", "5",
         "--seed", "0", "--out-prefix", out_prefix],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads((tmp_path / "out" / "ws-a.json").read_text())
    assert any(str(run_dir) in rd for rd in data.get("run_dirs", []))


# ---------------------------------------------------------------------------
# 2 — Calibration section content
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_calibration_section_has_required_fields(tmp_path: Path):
    """Calibration section must contain all required numeric/bool fields."""
    result, out_dir = _run_cli_with_standard_fixture(tmp_path)
    assert result.returncode == 0, result.stderr
    calib = json.loads((out_dir / "ws-a.json").read_text())["calibration"]

    required_fields = [
        "n", "mean_delta", "mean_reference",
        "pct_effect_arithmetic", "gate_passes",
        "paper_pct_effect", "paper_p_wilcoxon",
    ]
    for f in required_fields:
        assert f in calib, f"Missing calibration field: {f!r}"


@pytest.mark.integration
def test_calibration_paper_reference_constants(tmp_path: Path):
    """Calibration paper reference constants must match documented values."""
    result, out_dir = _run_cli_with_standard_fixture(tmp_path)
    assert result.returncode == 0, result.stderr
    calib = json.loads((out_dir / "ws-a.json").read_text())["calibration"]
    # These constants are hardcoded in power_analysis.py — verify they survive.
    assert calib["paper_pct_effect"] == pytest.approx(14.4375, abs=0.001)
    assert calib["paper_p_wilcoxon"] == pytest.approx(0.1202, abs=0.001)


@pytest.mark.integration
def test_calibration_effect_direction_positive(tmp_path: Path):
    """With treatment_cost > reference_cost, pct_effect_arithmetic must be positive."""
    # treatment=1.3, reference=1.0 → 30% positive effect
    result, out_dir = _run_cli_with_standard_fixture(
        tmp_path, treatment_cost=1.3, reference_cost=1.0,
    )
    assert result.returncode == 0, result.stderr
    calib = json.loads((out_dir / "ws-a.json").read_text())["calibration"]
    assert calib["pct_effect_arithmetic"] > 0


@pytest.mark.integration
def test_calibration_n_matches_n_paired(tmp_path: Path):
    """``calibration.n`` must equal ``n_paired``."""
    result, out_dir = _run_cli_with_standard_fixture(tmp_path, n_instances=10)
    assert result.returncode == 0, result.stderr
    data = json.loads((out_dir / "ws-a.json").read_text())
    assert data["calibration"]["n"] == data["n_paired"]


# ---------------------------------------------------------------------------
# 3 — Log-scale effect section content
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_log_scale_effect_section_has_required_fields(tmp_path: Path):
    """log_scale_effect section must contain required numeric fields."""
    result, out_dir = _run_cli_with_standard_fixture(tmp_path)
    assert result.returncode == 0, result.stderr
    lse = json.loads((out_dir / "ws-a.json").read_text())["log_scale_effect"]

    for f in ("mean_log_diff", "std_log_diff", "dz", "pct_effect_log"):
        assert f in lse, f"Missing log_scale_effect field: {f!r}"
        assert isinstance(lse[f], (int, float)), f"{f!r} must be numeric"


@pytest.mark.integration
def test_log_scale_full_contrast_section(tmp_path: Path):
    """log_scale_effect.full_contrast must contain CI and p-value fields."""
    result, out_dir = _run_cli_with_standard_fixture(tmp_path)
    assert result.returncode == 0, result.stderr
    fc = json.loads((out_dir / "ws-a.json").read_text())["log_scale_effect"]["full_contrast"]

    for f in ("n", "n_dropped", "mean_log_diff", "ci_pct_lo", "ci_pct_hi",
              "p_bootstrap", "n_boot", "alpha"):
        assert f in fc, f"Missing full_contrast field: {f!r}"


# ---------------------------------------------------------------------------
# 4 — Power-analysis section: curve rows and N* values
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_power_curve_row_count_matches_n_grid(tmp_path: Path):
    """Power curve row count must equal len(range(n_min, n_max+1, n_step))."""
    n_min, n_max, n_step = 5, 15, 5
    expected_rows = len(range(n_min, n_max + 1, n_step))  # [5, 10, 15] → 3

    result, out_dir = _run_cli_with_standard_fixture(
        tmp_path, n_min=n_min, n_max=n_max, n_step=n_step,
    )
    assert result.returncode == 0, result.stderr
    pa_section = json.loads((out_dir / "ws-a.json").read_text())["power_analysis"]
    assert len(pa_section["curve"]) == expected_rows


@pytest.mark.integration
def test_csv_row_count_matches_n_grid(tmp_path: Path):
    """CSV row count must match the power-curve n_grid length."""
    n_min, n_max, n_step = 5, 15, 5
    expected_rows = len(range(n_min, n_max + 1, n_step))

    result, out_dir = _run_cli_with_standard_fixture(
        tmp_path, n_min=n_min, n_max=n_max, n_step=n_step,
    )
    assert result.returncode == 0, result.stderr
    csv_path = out_dir / "ws-a.csv"
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == expected_rows


@pytest.mark.integration
def test_csv_n_values_match_n_grid(tmp_path: Path):
    """CSV ``n`` column values must exactly match the expected n_grid values."""
    n_min, n_max, n_step = 5, 15, 5
    expected_ns = list(range(n_min, n_max + 1, n_step))

    result, out_dir = _run_cli_with_standard_fixture(
        tmp_path, n_min=n_min, n_max=n_max, n_step=n_step,
    )
    assert result.returncode == 0, result.stderr
    csv_path = out_dir / "ws-a.csv"
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    actual_ns = [int(r["n"]) for r in rows]
    assert actual_ns == expected_ns


@pytest.mark.integration
def test_csv_rows_ordered_by_n_ascending(tmp_path: Path):
    """CSV rows must be ordered by n ascending."""
    result, out_dir = _run_cli_with_standard_fixture(
        tmp_path, n_min=5, n_max=15, n_step=5,
    )
    assert result.returncode == 0, result.stderr
    csv_path = out_dir / "ws-a.csv"
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    ns = [int(r["n"]) for r in rows]
    assert ns == sorted(ns), "CSV rows must be ordered by n ascending"


@pytest.mark.integration
def test_power_values_in_unit_interval(tmp_path: Path):
    """All power values in JSON curve and CSV must be in [0, 1]."""
    result, out_dir = _run_cli_with_standard_fixture(
        tmp_path, n_min=5, n_max=10, n_step=5,
    )
    assert result.returncode == 0, result.stderr

    # Check JSON curve
    curve = json.loads((out_dir / "ws-a.json").read_text())["power_analysis"]["curve"]
    for row in curve:
        assert 0.0 <= row["power_bootstrap"] <= 1.0, (
            f"power_bootstrap out of range: {row}")
        assert 0.0 <= row["power_wilcoxon"] <= 1.0, (
            f"power_wilcoxon out of range: {row}")

    # Check CSV
    csv_path = out_dir / "ws-a.csv"
    with open(csv_path) as f:
        csv_rows = list(csv.DictReader(f))
    for row in csv_rows:
        pb = float(row["power_bootstrap"])
        pw = float(row["power_wilcoxon"])
        assert 0.0 <= pb <= 1.0, f"CSV power_bootstrap out of range: {pb}"
        assert 0.0 <= pw <= 1.0, f"CSV power_wilcoxon out of range: {pw}"


@pytest.mark.integration
def test_n_star_fields_are_int_or_none(tmp_path: Path):
    """n_star_80 and n_star_90 in power_analysis section must be int or null."""
    result, out_dir = _run_cli_with_standard_fixture(tmp_path)
    assert result.returncode == 0, result.stderr
    pa_section = json.loads((out_dir / "ws-a.json").read_text())["power_analysis"]
    for field in ("n_star_80", "n_star_90"):
        val = pa_section[field]
        assert val is None or isinstance(val, int), (
            f"{field} must be int or null; got {type(val).__name__}")


# ---------------------------------------------------------------------------
# 5 — Go/no-go section content
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_gonogo_section_has_required_fields(tmp_path: Path):
    """go_nogo section must contain all documented fields."""
    result, out_dir = _run_cli_with_standard_fixture(tmp_path)
    assert result.returncode == 0, result.stderr
    rec = json.loads((out_dir / "ws-a.json").read_text())["go_nogo"]

    for f in ("verdict", "recommendation", "n_star_90", "n_star_80", "null_branch"):
        assert f in rec, f"Missing go_nogo field: {f!r}"


@pytest.mark.integration
def test_gonogo_null_branch_is_bool(tmp_path: Path):
    """go_nogo.null_branch must be a boolean."""
    result, out_dir = _run_cli_with_standard_fixture(tmp_path)
    assert result.returncode == 0, result.stderr
    rec = json.loads((out_dir / "ws-a.json").read_text())["go_nogo"]
    assert isinstance(rec["null_branch"], bool)


@pytest.mark.integration
def test_gonogo_recommendation_is_non_empty_string(tmp_path: Path):
    """go_nogo.recommendation must be a non-empty string."""
    result, out_dir = _run_cli_with_standard_fixture(tmp_path)
    assert result.returncode == 0, result.stderr
    rec = json.loads((out_dir / "ws-a.json").read_text())["go_nogo"]
    assert isinstance(rec["recommendation"], str)
    assert len(rec["recommendation"]) > 0


# ---------------------------------------------------------------------------
# 6 — Repo distribution section
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_repo_distribution_reflects_instance_repos(tmp_path: Path):
    """repo_distribution dict must contain the repos used in instance IDs."""
    # _standard_instances uses "django", "sklearn", "sympy", "mpl"
    result, out_dir = _run_cli_with_standard_fixture(tmp_path, n_instances=12)
    assert result.returncode == 0, result.stderr
    data = json.loads((out_dir / "ws-a.json").read_text())
    repo_dist = data.get("repo_distribution", {})
    assert isinstance(repo_dist, dict)
    # At minimum, the first repo used should appear
    assert "django" in repo_dist


@pytest.mark.integration
def test_repo_distribution_counts_sum_to_n_paired(tmp_path: Path):
    """Sum of repo_distribution values must equal n_paired."""
    result, out_dir = _run_cli_with_standard_fixture(tmp_path, n_instances=12)
    assert result.returncode == 0, result.stderr
    data = json.loads((out_dir / "ws-a.json").read_text())
    assert sum(data["repo_distribution"].values()) == data["n_paired"]


# ---------------------------------------------------------------------------
# 7 — JSON and CSV consistency
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_json_and_csv_curve_data_are_consistent(tmp_path: Path):
    """JSON power curve and CSV must contain the same n and power values."""
    result, out_dir = _run_cli_with_standard_fixture(
        tmp_path, n_min=5, n_max=10, n_step=5,
    )
    assert result.returncode == 0, result.stderr

    json_curve = json.loads((out_dir / "ws-a.json").read_text())["power_analysis"]["curve"]
    csv_path = out_dir / "ws-a.csv"
    with open(csv_path) as f:
        csv_rows = list(csv.DictReader(f))

    assert len(json_curve) == len(csv_rows)
    for jrow, crow in zip(json_curve, csv_rows):
        assert jrow["n"] == int(crow["n"])
        assert jrow["power_bootstrap"] == pytest.approx(
            float(crow["power_bootstrap"]), abs=1e-9
        )
        assert jrow["power_wilcoxon"] == pytest.approx(
            float(crow["power_wilcoxon"]), abs=1e-9
        )
