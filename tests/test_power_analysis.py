"""Unit tests for scripts/power_analysis.py (WS-A.1 power analysis, #307).

Hermetic and fast: synthesizes tiny SWE-bench-layout run dirs (JSONL + _test.txt)
with known costs and asserts:
- calibration gate recovers known arithmetic effect + p-value sign
- log-scale dz is consistent with the input data
- power curve is monotone increasing and N* detection is correct
- go/no-go verdict matches expected outcome
- JSON + CSV outputs are written with the correct schema

No real run dirs, no network.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

import power_analysis as pa  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers to synthesize run dirs
# ---------------------------------------------------------------------------


def _write_claude_jsonl(
    path: Path,
    *,
    instance: str,
    arm: str,
    cost: float,
    first_call_cache_read: int = 0,
) -> None:
    """Write a minimal claude-format JSONL file.

    ``first_call_cache_read=0`` means cold first call → cache-floor adjustment
    may increase the credited cache (reducing cost) when other instances are warm.
    We set it to a fixed value so adj_cost == cost in tests where all instances
    have the same first_call_cache_read (median = that value → moved = 0).
    """
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
    treatment_cost_fn,
    reference_cost_fn,
    treatment_arm: str = "onlycode",
    reference_arm: str = "baseline",
    treatment_cr: int = 100,  # uniform warm first_call_cache_read → no cache-floor adjustment
    reference_cr: int = 100,
) -> None:
    """Write a complete SWE-bench run dir with treatment and reference arms.

    By setting ``treatment_cr = reference_cr = 100`` (all warm with the same
    value), the cache-floor median equals that value, adj_cached = first_cr
    for every row, moved = 0 → cost_adj == cost_usd. This makes the tests
    deterministic without modelling the cache-floor mechanics.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    for iid in instances:
        stem_t = f"{iid}_{treatment_arm}_run1"
        stem_r = f"{iid}_{reference_arm}_run1"
        _write_claude_jsonl(
            run_dir / f"{stem_t}.jsonl",
            instance=iid, arm=treatment_arm, cost=treatment_cost_fn(iid),
            first_call_cache_read=treatment_cr,
        )
        (run_dir / f"{stem_t}_test.txt").write_text("ran tests\nPASS\n")
        _write_claude_jsonl(
            run_dir / f"{stem_r}.jsonl",
            instance=iid, arm=reference_arm, cost=reference_cost_fn(iid),
            first_call_cache_read=reference_cr,
        )
        (run_dir / f"{stem_r}_test.txt").write_text("ran tests\nPASS\n")


def _standard_instances(n: int = 20) -> list[str]:
    """Generate instance IDs spread across a few repos for stratification."""
    repos = ["django", "sphinx", "sklearn", "mpl", "sympy"]
    return [f"{repos[i % len(repos)]}__proj-{i:04d}" for i in range(n)]


# ---------------------------------------------------------------------------
# apply_cache_floor_adjustment (unit tests)
# ---------------------------------------------------------------------------


def test_cache_floor_no_cold_instances():
    """When all instances are warm with the same first_call_cache_read, no adjustment."""
    rows = [
        {"seed": "1", "arm": "onlycode", "cost_usd": 1.0,
         "first_call_input": 500, "first_call_cache_read": 100},
        {"seed": "1", "arm": "onlycode", "cost_usd": 2.0,
         "first_call_input": 500, "first_call_cache_read": 100},
    ]
    pa.apply_cache_floor_adjustment(rows)
    assert rows[0]["cost_adj"] == pytest.approx(1.0)
    assert rows[1]["cost_adj"] == pytest.approx(2.0)


def test_cache_floor_cold_instance_gets_credit():
    """Cold instance (first_call_cache_read=0) gets floored up to median of warm instances."""
    # Warm median = 200 tokens; gap = (3.00 - 0.30) / 1e6 = 2.7e-6 per token
    gap = (3.00 - 0.30) / 1_000_000
    rows = [
        {"seed": "1", "arm": "baseline", "cost_usd": 1.0,
         "first_call_input": 1000, "first_call_cache_read": 0},    # cold → gets credit
        {"seed": "1", "arm": "baseline", "cost_usd": 2.0,
         "first_call_input": 1000, "first_call_cache_read": 200},  # warm
        {"seed": "1", "arm": "baseline", "cost_usd": 3.0,
         "first_call_input": 1000, "first_call_cache_read": 200},  # warm
    ]
    pa.apply_cache_floor_adjustment(rows)
    # median(warm) = 200; cold row gets adj_cached=200, moved=200
    # cost_adj = 1.0 - 200 * gap
    expected_adj = 1.0 - 200 * gap
    assert rows[0]["cost_adj"] == pytest.approx(expected_adj, rel=1e-6)
    # Warm rows: moved=0 → unchanged
    assert rows[1]["cost_adj"] == pytest.approx(2.0)
    assert rows[2]["cost_adj"] == pytest.approx(3.0)


def test_cache_floor_none_fields_skipped():
    """Rows with None cost or missing fields are left unadjusted (cost_adj = cost_usd)."""
    rows = [
        {"seed": "1", "arm": "onlycode", "cost_usd": None,
         "first_call_input": 500, "first_call_cache_read": 100},
        {"seed": "1", "arm": "onlycode", "cost_usd": 1.0,
         "first_call_input": None, "first_call_cache_read": None},
    ]
    pa.apply_cache_floor_adjustment(rows)
    assert rows[0]["cost_adj"] is None
    assert rows[1]["cost_adj"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# load_paired_costs
# ---------------------------------------------------------------------------


def test_load_paired_costs_basic(tmp_path):
    """Costs are loaded and averaged across seeds; adj == cost when all warm."""
    instances = _standard_instances(10)
    # Seed 1: onlycode=1.2, baseline=1.0
    d1 = tmp_path / "full_run_seed_1"
    _make_run_dir(d1, instances=instances,
                  treatment_cost_fn=lambda _: 1.2,
                  reference_cost_fn=lambda _: 1.0)
    # Seed 2: onlycode=1.4, baseline=1.0 → mean onlycode = 1.3
    d2 = tmp_path / "full_run_seed_2"
    _make_run_dir(d2, instances=instances,
                  treatment_cost_fn=lambda _: 1.4,
                  reference_cost_fn=lambda _: 1.0)

    paired = pa.load_paired_costs([d1, d2])
    assert len(paired) == 10
    for iid in instances:
        t, r = paired[iid]
        assert r == pytest.approx(1.0, abs=1e-6)
        assert t == pytest.approx(1.3, abs=1e-4)


# ---------------------------------------------------------------------------
# calibration_check
# ---------------------------------------------------------------------------


def test_calibration_check_known_effect():
    """Arithmetic effect = 10% when treatment is uniformly 10% more expensive."""
    paired = {f"inst{i}": (1.1, 1.0) for i in range(20)}
    result = pa.calibration_check(paired)
    assert result["n"] == 20
    assert result["pct_effect_arithmetic"] == pytest.approx(10.0, abs=1e-6)
    # Wilcoxon detects uniform positive effect
    assert result["p_wilcoxon_arithmetic"] is not None
    assert result["p_wilcoxon_arithmetic"] < 0.05


def test_calibration_check_zero_effect():
    """Zero effect → arithmetic 0%, Wilcoxon p undefined (all zeros)."""
    paired = {f"inst{i}": (1.0, 1.0) for i in range(20)}
    result = pa.calibration_check(paired)
    assert result["pct_effect_arithmetic"] == pytest.approx(0.0, abs=1e-9)
    assert result["p_wilcoxon_arithmetic"] is None


def test_calibration_check_gate_tolerance():
    """Gate passes when arithmetic effect is near 14.4% (within ±1 pp) and p is near 0.12."""
    # Construct 100 paired instances where pct ≈ 14.44% and p ≈ noisy positive.
    # All identical deltas → p will be tiny (p < 0.05), so gate_passes = False
    # because p is not in [0.07, 0.20]. This is expected: gate only passes with real data.
    n = 100
    paired = {f"inst{i}": (1.1444 * (1.0 + 0.01 * i), 1.0 + 0.01 * i) for i in range(n)}
    result = pa.calibration_check(paired)
    # Effect is near 14.44%
    assert result["pct_effect_arithmetic"] == pytest.approx(14.44, abs=0.1)
    # Gate requires p ∈ [0.07, 0.20]; uniform deltas give p < 0.05 → gate fails
    assert result["gate_passes"] is False  # uniform deltas → too significant
    assert result["paper_pct_effect"] == 14.4375


# ---------------------------------------------------------------------------
# log_scale_effect
# ---------------------------------------------------------------------------


def test_log_scale_effect_known_ratio():
    """exp(mean_d) - 1 recovers the uniform cost ratio."""
    paired = {f"inst{i}": (1.2, 1.0) for i in range(50)}
    d, ids = pa.log_scale_effect(paired)
    assert len(d) == 50
    assert float(d.mean()) == pytest.approx(math.log(1.2), abs=1e-9)


def test_log_scale_effect_drops_nonpositive():
    """Instances with non-positive costs are dropped."""
    paired = {"good": (1.2, 1.0), "bad_t": (0.0, 1.0), "bad_r": (1.0, -0.5)}
    d, ids = pa.log_scale_effect(paired)
    assert len(d) == 1
    assert ids == ["good"]


# ---------------------------------------------------------------------------
# Repo stratification
# ---------------------------------------------------------------------------


def test_stratified_sample_size():
    """_stratified_sample always returns exactly n items."""
    rng = np.random.default_rng(0)
    d = np.ones(20)
    ids = [f"django__proj-{i}" for i in range(10)] + [f"astropy__proj-{i}" for i in range(10)]
    for n in (5, 10, 15, 20, 25):
        sample = pa._stratified_sample(d, ids, n, rng)
        assert len(sample) == n


def test_stratified_sample_single_repo():
    """With a single repo, stratified sampling degenerates to uniform with replacement."""
    rng = np.random.default_rng(1)
    d = np.arange(10, dtype=float)
    ids = [f"django__proj-{i}" for i in range(10)]
    sample = pa._stratified_sample(d, ids, 30, rng)
    assert len(sample) == 30


# ---------------------------------------------------------------------------
# Power curve monotonicity
# ---------------------------------------------------------------------------


def test_power_curve_monotone(tmp_path):
    """Power curve is weakly monotone increasing in N for a clear positive effect."""
    instances = _standard_instances(30)
    d1 = tmp_path / "full_run_seed_1"
    _make_run_dir(d1, instances=instances,
                  treatment_cost_fn=lambda _: 2.0,
                  reference_cost_fn=lambda _: 1.0)

    paired = pa.load_paired_costs([d1])
    d, ids = pa.log_scale_effect(paired)
    curve = pa.resampling_power(d, ids, n_grid=[5, 10, 15, 20],
                                n_boot=500, power_sims=200, alpha=0.05, seed=0)
    powers = [row["power_bootstrap"] for row in curve]
    for i in range(1, len(powers)):
        assert powers[i] >= powers[i - 1] - 0.15, f"Power dropped at N={curve[i]['n']}"


def test_power_curve_null_effect(tmp_path):
    """With no effect, power should be near alpha (≈0.05) at any N."""
    instances = _standard_instances(30)
    d1 = tmp_path / "full_run_seed_1"
    _make_run_dir(d1, instances=instances,
                  treatment_cost_fn=lambda _: 1.0,
                  reference_cost_fn=lambda _: 1.0)

    paired = pa.load_paired_costs([d1])
    d, ids = pa.log_scale_effect(paired)
    curve = pa.resampling_power(d, ids, n_grid=[10, 20],
                                n_boot=500, power_sims=200, alpha=0.05, seed=0)
    for row in curve:
        # Bootstrap p = 1 when d = 0 → all simulations fail to reject → power ≈ 0
        assert row["power_bootstrap"] < 0.20


# ---------------------------------------------------------------------------
# find_n_star
# ---------------------------------------------------------------------------


def test_find_n_star_exact():
    """N* is the first N that reaches the threshold."""
    curve = [
        {"n": 10, "power_bootstrap": 0.50, "power_wilcoxon": 0.45},
        {"n": 20, "power_bootstrap": 0.75, "power_wilcoxon": 0.70},
        {"n": 30, "power_bootstrap": 0.90, "power_wilcoxon": 0.88},
        {"n": 40, "power_bootstrap": 0.95, "power_wilcoxon": 0.93},
    ]
    assert pa.find_n_star(curve, 0.90) == 30
    # 0.75 < 0.80 at N=20; N=30 (0.90 ≥ 0.80) is the first to cross
    assert pa.find_n_star(curve, 0.80) == 30
    assert pa.find_n_star(curve, 0.96) is None  # never reached


def test_find_n_star_never_reached():
    """Returns None when threshold is not met."""
    curve = [{"n": 10, "power_bootstrap": 0.50, "power_wilcoxon": 0.45}]
    assert pa.find_n_star(curve, 0.90) is None


# ---------------------------------------------------------------------------
# go_nogo_recommendation
# ---------------------------------------------------------------------------


def test_go_nogo_powered_subset():
    rec = pa.go_nogo_recommendation(n_star_90=80, n_star_80=60, n_available=100)
    assert rec["verdict"] == "powered_subset"
    assert rec["null_branch"] is False
    assert rec["n_star_90"] == 80


def test_go_nogo_full_pool():
    rec = pa.go_nogo_recommendation(n_star_90=150, n_star_80=100, n_available=100)
    assert rec["verdict"] == "full_pool"
    assert rec["null_branch"] is False


def test_go_nogo_null_branch():
    rec = pa.go_nogo_recommendation(n_star_90=None, n_star_80=None, n_available=100)
    assert rec["verdict"] == "null_branch"
    assert rec["null_branch"] is True


# ---------------------------------------------------------------------------
# build_report integration (small synthetic data)
# ---------------------------------------------------------------------------


def test_build_report_end_to_end(tmp_path):
    """build_report runs without error on small synthetic data and returns expected schema."""
    instances = _standard_instances(20)
    d1 = tmp_path / "full_run_seed_1"
    _make_run_dir(d1, instances=instances,
                  treatment_cost_fn=lambda _: 1.3,
                  reference_cost_fn=lambda _: 1.0)
    d2 = tmp_path / "full_run_seed_2"
    _make_run_dir(d2, instances=instances,
                  treatment_cost_fn=lambda _: 1.3,
                  reference_cost_fn=lambda _: 1.0)

    rep = pa.build_report(
        [d1, d2],
        n_boot=500,
        power_sims=100,
        n_min=5,
        n_max=20,
        n_step=5,
        seed=0,
    )

    # Schema checks
    assert "calibration" in rep
    assert "log_scale_effect" in rep
    assert "power_analysis" in rep
    assert "go_nogo" in rep
    assert rep["n_paired"] == 20

    # Calibration: +30% arithmetic effect
    calib = rep["calibration"]
    assert calib["pct_effect_arithmetic"] == pytest.approx(30.0, abs=0.1)

    # Log-scale effect: exp(log(1.3)) - 1 = 30%
    log_eff = rep["log_scale_effect"]
    assert log_eff["pct_effect_log"] == pytest.approx(30.0, abs=0.1)

    # Power curve: 4 entries (5, 10, 15, 20)
    pa_sec = rep["power_analysis"]
    assert len(pa_sec["curve"]) == 4

    # go_nogo has a verdict
    assert rep["go_nogo"]["verdict"] in ("powered_subset", "full_pool", "null_branch")

    # repo_distribution should reflect our synthetic instance names
    assert "django" in rep["repo_distribution"]


# ---------------------------------------------------------------------------
# Output files (JSON + CSV)
# ---------------------------------------------------------------------------


def test_write_outputs_creates_files(tmp_path):
    """_write_outputs creates both JSON and CSV with correct schema."""
    rep = {
        "treatment": "onlycode",
        "reference": "baseline",
        "run_dirs": [],
        "n_paired": 10,
        "repo_distribution": {"django": 10},
        "calibration": {
            "n": 10, "mean_delta": 0.1, "mean_reference": 1.0,
            "pct_effect_arithmetic": 10.0, "p_wilcoxon_arithmetic": 0.05,
            "gate_passes": False, "paper_pct_effect": 14.4375, "paper_p_wilcoxon": 0.1202,
        },
        "log_scale_effect": {
            "mean_log_diff": 0.095, "std_log_diff": 0.1, "dz": 0.95,
            "pct_effect_log": 9.97,
            "full_contrast": {
                "n": 10, "n_dropped": 0, "mean_log_diff": 0.095,
                "pct_effect": 9.97, "ci_pct_lo": 5.0, "ci_pct_hi": 15.0,
                "p_bootstrap": 0.02, "p_wilcoxon": 0.03,
                "n_boot": 500, "alpha": 0.05, "significant": True,
            },
        },
        "power_analysis": {
            "n_grid": [5, 10], "n_boot": 500, "power_sims": 100,
            "alpha": 0.05, "seed": 0, "n_star_80": 5, "n_star_90": 10,
            "curve": [
                {"n": 5, "power_bootstrap": 0.75, "power_wilcoxon": 0.70},
                {"n": 10, "power_bootstrap": 0.91, "power_wilcoxon": 0.89},
            ],
        },
        "go_nogo": {
            "verdict": "powered_subset",
            "recommendation": "Run N=10.",
            "n_star_90": 10, "n_star_80": 5, "null_branch": False,
        },
    }

    out_prefix = str(tmp_path / "ws-a")
    pa._write_outputs(rep, out_prefix)

    json_path = tmp_path / "ws-a.json"
    csv_path = tmp_path / "ws-a.csv"
    assert json_path.exists()
    assert csv_path.exists()

    loaded = json.loads(json_path.read_text())
    assert loaded["go_nogo"]["verdict"] == "powered_subset"

    import csv as csv_mod
    with open(csv_path) as f:
        rows = list(csv_mod.DictReader(f))
    assert len(rows) == 2
    assert rows[0]["n"] == "5"
    assert float(rows[1]["power_bootstrap"]) == pytest.approx(0.91)


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------


def test_cli_main_runs(tmp_path, capsys):
    """CLI main() writes outputs and prints a report without crashing."""
    instances = _standard_instances(10)
    d1 = tmp_path / "full_run_seed_1"
    _make_run_dir(d1, instances=instances,
                  treatment_cost_fn=lambda _: 1.15,
                  reference_cost_fn=lambda _: 1.0)

    out_prefix = str(tmp_path / "out" / "ws-a")
    pa.main([
        "--runs", str(d1),
        "--n-boot", "200",
        "--power-sims", "50",
        "--n-min", "5",
        "--n-max", "10",
        "--n-step", "5",
        "--seed", "0",
        "--out-prefix", out_prefix,
    ])

    captured = capsys.readouterr()
    assert "Calibration gate" in captured.out
    assert (tmp_path / "out" / "ws-a.json").exists()
    assert (tmp_path / "out" / "ws-a.csv").exists()
