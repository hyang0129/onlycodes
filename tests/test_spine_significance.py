"""Unit tests for scripts/spine_significance.py (#299 closing report).

Hermetic: synthesizes tiny SWE-bench-layout run dirs (JSONL + _test.txt) with
known costs/verdicts and asserts the report structure + recovered effect. No
network, no real repos.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import spine_significance as ss  # noqa: E402


def _write_run(run_dir: Path, rows: list[dict]) -> None:
    """rows: list of {instance, arm, run, cost, verdict}. cache_read=0 so the
    cache-adjusted cost equals `cost` exactly (deterministic)."""
    run_dir.mkdir(parents=True, exist_ok=True)
    for r in rows:
        stem = f"{r['instance']}_{r['arm']}_run{r['run']}"
        jsonl = run_dir / f"{stem}.jsonl"
        lines = [
            {"type": "meta", "instance_id": r["instance"], "arm": r["arm"],
             "run": r["run"], "agent_surface": "claude_code"},
            {"type": "assistant", "message": {
                "id": f"m_{stem}", "model": "claude-sonnet-4-6",
                "usage": {"input_tokens": 5, "cache_read_input_tokens": 0,
                          "cache_creation_input_tokens": 10, "output_tokens": 7}}},
            {"type": "result", "total_cost_usd": r["cost"], "num_turns": 3,
             "usage": {"input_tokens": 5, "output_tokens": 7}},
        ]
        jsonl.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
        (run_dir / f"{stem}_test.txt").write_text(f"ran tests\n{r['verdict']}\n")


def _make_seed(run_dir: Path, *, baseline_cost: float, onlycode_cost: float,
               instances: int, verdict: str = "PASS") -> None:
    rows = []
    for k in range(instances):
        iid = f"repo__proj-{k:04d}"
        rows.append({"instance": iid, "arm": "baseline", "run": 1,
                     "cost": baseline_cost, "verdict": verdict})
        rows.append({"instance": iid, "arm": "onlycode", "run": 1,
                     "cost": onlycode_cost, "verdict": verdict})
    _write_run(run_dir, rows)


def test_recovers_known_cost_effect(tmp_path):
    # onlycode costs 20% more than baseline on every instance, across 3 seeds.
    seeds = []
    for s in (1, 2, 3):
        d = tmp_path / f"seed_{s}"
        _make_seed(d, baseline_cost=1.0, onlycode_cost=1.2, instances=12)
        seeds.append(d)

    rep = ss.build_report(
        seeds, agent="claude", mode="claude", reference="baseline",
        treatments=["onlycode"], keep=None, bound_pct=10.0,
        n_boot=2000, alpha=0.05, seed=0,
    )
    assert rep["n_seeds"] == 3
    (c,) = rep["contrasts"]
    assert c["treatment"] == "onlycode"
    cc = c["cost_contrast"]
    assert cc["n"] == 12
    assert cc["pct_effect"] == pytest.approx(20.0, abs=1e-6)
    assert cc["significant"] is True
    # +20% exceeds the ±10% equivalence bound → not equivalent.
    assert c["equivalence"]["equivalent"] is False
    # All PASS under both arms → no discordant pairs, McNemar p == 1.
    mc = c["pass_rate_guard"]
    assert mc["pass_rate_treatment"] == 1.0 and mc["pass_rate_reference"] == 1.0
    assert mc["mcnemar_p"] == 1.0


def test_filter_restricts_instances(tmp_path):
    d = tmp_path / "seed_1"
    _make_seed(d, baseline_cost=1.0, onlycode_cost=1.1, instances=10)
    keep = {"repo__proj-0000", "repo__proj-0001", "repo__proj-0002"}
    rep = ss.build_report(
        [d], agent="claude", mode="claude", reference="baseline",
        treatments=["onlycode"], keep=keep, bound_pct=10.0,
        n_boot=500, alpha=0.05, seed=0,
    )
    assert rep["contrasts"][0]["cost_contrast"]["n"] == 3


def test_outputs_written(tmp_path):
    d = tmp_path / "seed_1"
    _make_seed(d, baseline_cost=1.0, onlycode_cost=1.2, instances=5)
    rep = ss.build_report(
        [d], agent="claude", mode="claude", reference="baseline",
        treatments=["onlycode"], keep=None, bound_pct=10.0,
        n_boot=500, alpha=0.05, seed=0,
    )
    prefix = tmp_path / "out" / "claude"
    ss._write_outputs(rep, str(prefix))
    assert prefix.with_suffix(".json").is_file()
    assert prefix.with_suffix(".csv").is_file()
    loaded = json.loads(prefix.with_suffix(".json").read_text())
    assert loaded["contrasts"][0]["cost_contrast"]["pct_effect"] == pytest.approx(20.0, abs=1e-6)


def test_resolve_filter_file(tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("# subset\nrepo__proj-0001\nrepo__proj-0002  # kept\n\n")
    assert ss._resolve_filter(f"@{f}") == {"repo__proj-0001", "repo__proj-0002"}
    assert ss._resolve_filter("a,b ,c") == {"a", "b", "c"}
    assert ss._resolve_filter(None) is None


def test_resolve_filter_empty_file_errors(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("# only a comment\n\n   \n")
    with pytest.raises(SystemExit):
        ss._resolve_filter(f"@{f}")
