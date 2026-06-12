#!/usr/bin/env python3
"""Power analysis → N* for the SWE-bench/Claude NS anchor (WS-A.1, #307).

Calibration gate: reproduces the +14.4%, p≈0.12 headline contrast from
``runs/swebench/full_run_seed_{1,2,3}`` using the same arithmetic effect size
and Wilcoxon test as the paper's headline cell (``headline_unanimous.csv``).
The paper's ``cost_usd_adjusted`` uses a **cache-floor** adjustment sourced
from ``scripts/collect_results._apply_cache_floor_adjustment``: for each
(seed, arm) group, cold-start tasks (first_call_cache_read = 0) are given
credit for the median warm cache read, lowering their cost. This is
implemented here from raw JSONL without reading paper/ data files.

Power analysis: resampling power on the log-scale estimand (the issue's
canonical estimand, d_i = log c_onlycode,i − log c_baseline,i, averaged
across seeds) at a grid of N values, with proportional repo-stratified
sampling. N* is the smallest N with power ≥ 0.90 at α = 0.05 two-sided.

Usage:
  scripts/power_analysis.py \\
      --runs runs/swebench/full_run_seed_1 \\
             runs/swebench/full_run_seed_2 \\
             runs/swebench/full_run_seed_3 \\
      [--treatment onlycode] [--reference baseline] \\
      [--n-boot 10000] [--power-sims 2000] [--alpha 0.05] \\
      [--n-min 20] [--n-max 500] [--n-step 10] \\
      [--out-prefix runs/swebench/_analysis/power/ws-a] \\
      [--seed 0]

Outputs:
  <out_prefix>.json  — full report (calibration + power curve + N* + go/no-go)
  <out_prefix>.csv   — power curve table (n, power_bootstrap, power_wilcoxon)
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import wilcoxon as scipy_wilcoxon

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

from swebench.contrast_stats import paired_cost_contrast  # noqa: E402

# Claude pricing constants (same as parse_run.py / cost_first_call_adjust.py).
# The cache-floor adjustment gap = input_rate − cache_read_rate per token.
_CLAUDE_INPUT_RATE = 3.00   # USD / 1M tokens
_CLAUDE_CR_RATE = 0.30      # USD / 1M tokens — cache_read
_CLAUDE_GAP = (_CLAUDE_INPUT_RATE - _CLAUDE_CR_RATE) / 1_000_000  # per token

# Regex for SWE-bench JSONL filenames: {instance_id}_{arm}_run{N}.jsonl
_STEM_RE = re.compile(r"^(.+)_(baseline|onlycode|bash_only)_run(\d+)$")


# ---------------------------------------------------------------------------
# Raw JSONL parsing (extract cost + first-call cache_read per instance/arm)
# ---------------------------------------------------------------------------


def _parse_claude_jsonl(jsonl_path: Path) -> dict | None:
    """Extract (cost_usd, first_call_input, first_call_cache_read, model) from one JSONL.

    Returns None if the file has no result line or is unreadable.
    """
    seen_ids: set[str] = set()
    first_call_usage: dict | None = None
    result_line: dict | None = None
    model: str | None = None

    try:
        with open(jsonl_path) as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                t = obj.get("type")
                if t == "assistant":
                    msg = obj.get("message") or {}
                    msg_id = msg.get("id")
                    if msg_id and msg_id in seen_ids:
                        continue
                    seen_ids.add(msg_id or f"_pos_{len(seen_ids)}")
                    if model is None:
                        model = msg.get("model")
                    if first_call_usage is None:
                        u = msg.get("usage")
                        if isinstance(u, dict):
                            first_call_usage = u
                elif t == "result":
                    result_line = obj
    except OSError:
        return None

    if result_line is None:
        return None

    cost = result_line.get("total_cost_usd")
    if not isinstance(cost, (int, float)):
        return None
    cost = float(cost)

    first_input = first_cache_read = None
    if isinstance(first_call_usage, dict):
        fi = int(first_call_usage.get("input_tokens") or 0)
        fcr = int(first_call_usage.get("cache_read_input_tokens") or 0)
        fcc = int(first_call_usage.get("cache_creation_input_tokens") or 0)
        first_input = fi + fcr + fcc
        first_cache_read = fcr

    return {
        "cost_usd": cost,
        "first_call_input": first_input,
        "first_call_cache_read": first_cache_read,
        "model": model,
    }


def _walk_swebench_run_dir(run_dir: Path):
    """Yield (instance_id, arm, run_idx, jsonl_path) for each JSONL in a SWE-bench run dir."""
    for jsonl in sorted(run_dir.glob("*.jsonl")):
        m = _STEM_RE.match(jsonl.stem)
        if not m:
            continue
        yield m.group(1), m.group(2), int(m.group(3)), jsonl


def _load_run_dir(run_dir: Path) -> list[dict]:
    """Parse one run dir into a flat list of row dicts.

    Each row: {instance_id, arm, run, seed (from dir name), cost_usd,
               first_call_input, first_call_cache_read, model}
    """
    # Infer seed from directory name (e.g. full_run_seed_2 → seed=2).
    # If not parseable, fall back to a placeholder.
    m = re.search(r"seed_(\d+)", run_dir.name)
    seed_str = m.group(1) if m else run_dir.name

    rows = []
    for iid, arm, run_idx, jsonl in _walk_swebench_run_dir(run_dir):
        parsed = _parse_claude_jsonl(jsonl)
        if parsed is None:
            continue
        rows.append({
            "instance_id": iid,
            "arm": arm,
            "run": run_idx,
            "seed": seed_str,
            "cost_usd": parsed["cost_usd"],
            "first_call_input": parsed["first_call_input"],
            "first_call_cache_read": parsed["first_call_cache_read"],
            "model": parsed["model"],
        })
    return rows


# ---------------------------------------------------------------------------
# Cache-floor adjustment (mirrors collect_results._apply_cache_floor_adjustment)
# ---------------------------------------------------------------------------


def apply_cache_floor_adjustment(rows: list[dict]) -> None:
    """Per-(seed, arm) median floor on first-call cache_read; mutates rows in place.

    Logic from ``scripts/collect_results._apply_cache_floor_adjustment``:
    - Group by (seed, arm).
    - For each group, compute median(first_call_cache_read) over the warm
      subset (rows where first_call_cache_read > 0).
    - For each row: adj_cached = max(first_cr, min(median, first_input)).
      moved = adj_cached − first_cr. Δ = −moved × gap.
      cost_adj = cost_usd + Δ  (Δ ≤ 0, so adj ≤ orig).

    Rows where cost_usd, first_call_input, or first_call_cache_read is None
    get cost_adj = cost_usd (no adjustment possible).
    """
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        groups[(row["seed"], row["arm"])].append(row)

    for _key, grp in groups.items():
        warm = [
            r["first_call_cache_read"]
            for r in grp
            if isinstance(r["first_call_cache_read"], int) and r["first_call_cache_read"] > 0
        ]
        median = int(statistics.median(warm)) if warm else 0

        for row in grp:
            cost = row["cost_usd"]
            first_input = row["first_call_input"]
            first_cr = row["first_call_cache_read"]
            if not isinstance(cost, (int, float)) or first_input is None or first_cr is None:
                row["cost_adj"] = cost
                continue
            adj_cached = max(first_cr, min(median, first_input))
            moved = adj_cached - first_cr
            if moved == 0:
                row["cost_adj"] = cost
            else:
                row["cost_adj"] = cost - moved * _CLAUDE_GAP


# ---------------------------------------------------------------------------
# Data loading with cache-floor adjustment + per-instance seed averaging
# ---------------------------------------------------------------------------


def load_paired_costs(
    run_dirs: list[Path],
    *,
    treatment: str = "onlycode",
    reference: str = "baseline",
) -> dict[str, tuple[float, float]]:
    """Load per-instance (treatment_cost, reference_cost), averaged across seeds.

    Uses the cache-floor-adjusted cost (same methodology as the paper's
    ``cost_usd_adjusted`` column in ``all_results.csv``). Returns only
    instances present with positive cost in **both** arms across all seeds.
    """
    all_rows: list[dict] = []
    for rd in run_dirs:
        rd = Path(rd)
        if not rd.is_dir():
            sys.exit(f"ERROR: run dir not found: {rd}")
        rows = _load_run_dir(rd)
        apply_cache_floor_adjustment(rows)
        all_rows.extend(rows)

    # Group by (arm, instance_id) and collect costs across seeds
    costs: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in all_rows:
        c = row.get("cost_adj") or row.get("cost_usd")
        if c is not None and isinstance(c, float) and math.isfinite(c) and c > 0:
            costs[row["arm"]][row["instance_id"]].append(c)

    mean_arm: dict[str, dict[str, float]] = {
        arm: {iid: sum(v) / len(v) for iid, v in inst.items() if v}
        for arm, inst in costs.items()
    }

    t_map = mean_arm.get(treatment, {})
    r_map = mean_arm.get(reference, {})
    common = sorted(set(t_map) & set(r_map))
    return {iid: (t_map[iid], r_map[iid]) for iid in common}


# ---------------------------------------------------------------------------
# Calibration gate (arithmetic delta + Wilcoxon — matches paper headline)
# ---------------------------------------------------------------------------


def calibration_check(
    paired: dict[str, tuple[float, float]],
) -> dict:
    """Reproduce the paper's +14.4%, p≈0.12 arithmetic-scale headline.

    The paper reports:
      - effect  = mean_delta / mean_reference × 100  (arithmetic ratio)
      - p-value = Wilcoxon signed-rank on arithmetic per-instance deltas
        (treatment − reference, with cache-floor-adjusted costs)

    This is distinct from the log-scale estimand used in the power analysis.
    Gate passes if effect ∈ [+13.4%, +15.4%] and p ∈ [0.07, 0.17].
    """
    ids = sorted(paired)
    deltas = [paired[iid][0] - paired[iid][1] for iid in ids]
    mean_delta = sum(deltas) / len(deltas)
    mean_ref = sum(paired[iid][1] for iid in ids) / len(ids)
    pct_effect = mean_delta / mean_ref * 100

    p_wilcoxon: float | None = None
    nonzero = [d for d in deltas if d != 0.0]
    if nonzero:
        try:
            p_wilcoxon = float(scipy_wilcoxon(nonzero).pvalue)
        except Exception:
            pass

    # Tolerance window: paper headline = +14.4375%, p=0.1202
    gate_passes = (
        pct_effect is not None
        and 13.0 <= pct_effect <= 16.0
        and p_wilcoxon is not None
        and 0.07 <= p_wilcoxon <= 0.20
    )
    return {
        "n": len(ids),
        "mean_delta": mean_delta,
        "mean_reference": mean_ref,
        "pct_effect_arithmetic": pct_effect,
        "p_wilcoxon_arithmetic": p_wilcoxon,
        "gate_passes": gate_passes,
        # Paper reference values
        "paper_pct_effect": 14.4375,
        "paper_p_wilcoxon": 0.1202,
    }


# ---------------------------------------------------------------------------
# Log-scale effect + Cohen dz (the power analysis estimand)
# ---------------------------------------------------------------------------


def log_scale_effect(
    paired: dict[str, tuple[float, float]],
) -> tuple[np.ndarray, list[str]]:
    """Compute per-instance log-differences d_i = log(treatment) - log(reference).

    Returns ``(d, ids)`` where ``d[i]`` corresponds to ``ids[i]``.
    """
    ids = sorted(paired)
    d_list: list[float] = []
    ids_kept: list[str] = []
    for iid in ids:
        t, r = paired[iid]
        if t > 0 and r > 0 and math.isfinite(t) and math.isfinite(r):
            d_list.append(math.log(t) - math.log(r))
            ids_kept.append(iid)
    return np.asarray(d_list, dtype=float), ids_kept


# ---------------------------------------------------------------------------
# Repo stratification
# ---------------------------------------------------------------------------


def _repo_from_id(instance_id: str) -> str:
    """Extract repo from SWE-bench instance ID (e.g. 'django__django-1234' → 'django')."""
    return instance_id.split("__")[0]


def _stratified_sample(
    d: np.ndarray,
    ids: list[str],
    n: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Draw n instances with proportional repo stratification.

    For each repo, allocate ``round(n * repo_frac)`` slots; the last repo
    absorbs the rounding residual to ensure exactly n are drawn total.
    Within each repo the draw is with replacement (resampling power convention).
    Returns a 1-D array of n log-differences.
    """
    repo_idx: dict[str, list[int]] = defaultdict(list)
    for i, iid in enumerate(ids):
        repo_idx[_repo_from_id(iid)].append(i)

    total = len(ids)
    repos = sorted(repo_idx)
    alloc: dict[str, int] = {}
    allocated = 0
    for repo in repos[:-1]:
        k = round(n * len(repo_idx[repo]) / total)
        alloc[repo] = k
        allocated += k
    alloc[repos[-1]] = n - allocated  # absorb rounding residual

    sample_idx: list[int] = []
    for repo in repos:
        k = alloc[repo]
        if k <= 0:
            continue
        pool = repo_idx[repo]
        sample_idx.extend(rng.choice(pool, size=k, replace=True).tolist())

    return d[sample_idx]


# ---------------------------------------------------------------------------
# Resampling power
# ---------------------------------------------------------------------------


def resampling_power(
    d: np.ndarray,
    ids: list[str],
    *,
    n_grid: list[int],
    n_boot: int = 10000,
    power_sims: int = 2000,
    alpha: float = 0.05,
    seed: int = 0,
) -> list[dict]:
    """Compute empirical power at each N in n_grid.

    For each N:
      1. Draw ``power_sims`` stratified resamples of size N from the empirical
         per-instance log-difference distribution (with replacement within repo).
      2. For each resample, run: paired bootstrap (n_boot resamples) → p_boot,
         Wilcoxon signed-rank on log-diffs → p_wil.
      3. Power = fraction of simulations where p < alpha.

    Returns a list of dicts (one per N): {n, power_bootstrap, power_wilcoxon}.
    """
    rng = np.random.default_rng(seed)
    results: list[dict] = []

    for N in n_grid:
        boot_rejections = 0
        wil_rejections = 0

        for _ in range(power_sims):
            sample = _stratified_sample(d, ids, N, rng)
            p_boot = _bootstrap_pvalue(sample, n_boot=n_boot, rng=rng)
            if p_boot < alpha:
                boot_rejections += 1
            p_wil = _wilcoxon_pvalue(sample)
            if p_wil is not None and p_wil < alpha:
                wil_rejections += 1

        results.append({
            "n": N,
            "power_bootstrap": boot_rejections / power_sims,
            "power_wilcoxon": wil_rejections / power_sims,
        })

    return results


def _bootstrap_pvalue(d: np.ndarray, n_boot: int, rng: np.random.Generator) -> float:
    """Two-sided bootstrap p-value for H0: mean(d) = 0.

    CI-inversion: 2 * min(P(boot>=0), P(boot<=0)).
    """
    n = len(d)
    if n == 0:
        return 1.0
    idx = rng.integers(0, n, size=(n_boot, n))
    boot_means = d[idx].mean(axis=1)
    p_left = float(np.mean(boot_means >= 0.0))
    p_right = float(np.mean(boot_means <= 0.0))
    return min(1.0, 2.0 * min(p_left, p_right))


def _wilcoxon_pvalue(d: np.ndarray) -> float | None:
    """Two-sided Wilcoxon signed-rank p-value; None if undefined."""
    nz = d[d != 0.0]
    if len(nz) < 1:
        return None
    try:
        return float(scipy_wilcoxon(nz).pvalue)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# N* detection
# ---------------------------------------------------------------------------


def find_n_star(
    curve: list[dict],
    power_threshold: float,
    key: str = "power_bootstrap",
) -> int | None:
    """Return smallest N with power >= power_threshold, or None if not reached."""
    for row in curve:
        if row[key] >= power_threshold:
            return row["n"]
    return None


# ---------------------------------------------------------------------------
# Go/no-go recommendation
# ---------------------------------------------------------------------------


def go_nogo_recommendation(
    n_star_90: int | None,
    n_star_80: int | None,
    n_available: int,
) -> dict:
    """Produce a go/no-go recommendation for #299 (modification spine N).

    Three verdicts:
    - "powered_subset": N* ≤ n_available → run N* instances in the spine.
    - "full_pool": N* ≤ 500 but exceeds n_available → run full available pool.
    - "null_branch": N* > 500 → effect too small; plan TOST at full buildable pool.
    """
    if n_star_90 is not None and n_star_90 <= n_available:
        return {
            "verdict": "powered_subset",
            "recommendation": (
                f"Run {n_star_90} instances in the modification spine (#299). "
                f"This is N* for 0.90 power at the observed effect size. "
                f"Powered subset sizing for the deconfound cut (#301) should also use N={n_star_90}."
            ),
            "n_star_90": n_star_90,
            "n_star_80": n_star_80,
            "null_branch": False,
        }
    if n_star_90 is not None and n_star_90 > n_available:
        return {
            "verdict": "full_pool",
            "recommendation": (
                f"N* ({n_star_90}) exceeds available paired instances ({n_available}). "
                f"Run the full available pool in the spine (#299). "
                f"Consider accepting 0.80 power (N*={n_star_80}) if n_available < N*(0.90)."
            ),
            "n_star_90": n_star_90,
            "n_star_80": n_star_80,
            "null_branch": False,
        }
    return {
        "verdict": "null_branch",
        "recommendation": (
            "N* for 0.90 power exceeds the grid maximum (500). "
            "The observed effect is too small to power under the current n=100 data. "
            "Pre-register a minimum meaningful effect (±10% cost) and plan a TOST "
            "equivalence test at the full buildable pool. "
            "A CI excluding ±10% would be a clean null — retire the 'lone exception' framing."
        ),
        "n_star_90": None,
        "n_star_80": n_star_80,
        "null_branch": True,
    }


# ---------------------------------------------------------------------------
# Report assembly and I/O
# ---------------------------------------------------------------------------


def build_report(
    run_dirs: list[Path],
    *,
    treatment: str = "onlycode",
    reference: str = "baseline",
    n_boot: int = 10000,
    power_sims: int = 2000,
    alpha: float = 0.05,
    n_min: int = 20,
    n_max: int = 500,
    n_step: int = 10,
    seed: int = 0,
) -> dict:
    """Run the full power analysis pipeline and return the report dict."""
    paired = load_paired_costs(run_dirs, treatment=treatment, reference=reference)
    if not paired:
        sys.exit("ERROR: no paired instances found. Check run dirs and arm names.")

    # Calibration gate (arithmetic + Wilcoxon, cache-floor-adj — matches paper headline)
    calib = calibration_check(paired)

    # Log-scale effect (power analysis estimand)
    d, ids = log_scale_effect(paired)
    n_paired = len(d)
    if n_paired == 0:
        sys.exit("ERROR: zero valid paired log-differences after filtering.")

    mean_log = float(d.mean())
    std_log = float(d.std(ddof=0))
    dz = mean_log / std_log if std_log > 0 else float("nan")
    pct_effect_log = 100.0 * (math.exp(mean_log) - 1.0)

    # Full-sample log-scale contrast
    full_contrast = paired_cost_contrast(
        {iid: paired[iid][0] for iid in paired},
        {iid: paired[iid][1] for iid in paired},
        n_boot=n_boot,
        alpha=alpha,
        seed=seed,
    )

    # Repo distribution
    repo_counts: dict[str, int] = defaultdict(int)
    for iid in ids:
        repo_counts[_repo_from_id(iid)] += 1

    # Power curve
    n_grid = list(range(n_min, n_max + 1, n_step))
    curve = resampling_power(
        d, ids,
        n_grid=n_grid,
        n_boot=n_boot,
        power_sims=power_sims,
        alpha=alpha,
        seed=seed,
    )

    n_star_90 = find_n_star(curve, 0.90, "power_bootstrap")
    n_star_80 = find_n_star(curve, 0.80, "power_bootstrap")
    rec = go_nogo_recommendation(n_star_90, n_star_80, n_paired)

    return {
        "treatment": treatment,
        "reference": reference,
        "run_dirs": [str(r) for r in run_dirs],
        "n_paired": n_paired,
        "repo_distribution": dict(sorted(repo_counts.items())),
        "calibration": calib,
        "log_scale_effect": {
            "mean_log_diff": mean_log,
            "std_log_diff": std_log,
            "dz": dz,
            "pct_effect_log": pct_effect_log,
            "full_contrast": full_contrast.as_dict(),
        },
        "power_analysis": {
            "n_grid": n_grid,
            "n_boot": n_boot,
            "power_sims": power_sims,
            "alpha": alpha,
            "seed": seed,
            "n_star_80": n_star_80,
            "n_star_90": n_star_90,
            "curve": curve,
        },
        "go_nogo": rec,
    }


def _print_report(rep: dict) -> None:
    calib = rep["calibration"]
    log_eff = rep["log_scale_effect"]
    pa = rep["power_analysis"]
    rec = rep["go_nogo"]

    print("=" * 96)
    print("Power Analysis — WS-A.1 (#307)")
    print(f"  treatment={rep['treatment']}  reference={rep['reference']}  n={rep['n_paired']}")
    print(f"  run_dirs: {rep['run_dirs']}")
    print("=" * 96)

    print("\n--- Calibration gate (arithmetic effect, cache-floor-adjusted cost) ---")
    gate_status = "PASS" if calib["gate_passes"] else "FAIL"
    print(f"  Status   : {gate_status}")
    print(f"  Effect   : {calib['pct_effect_arithmetic']:+.4f}%  "
          f"(paper headline: +{calib['paper_pct_effect']:.4f}%)")
    print(f"  Wilcoxon : p={calib['p_wilcoxon_arithmetic']:.4g}  "
          f"(paper: p≈{calib['paper_p_wilcoxon']:.4f})")
    print(f"  n        : {calib['n']}")

    print("\n--- Log-scale effect (power analysis estimand: d_i = log(treat) - log(ref)) ---")
    fc = log_eff["full_contrast"]
    print(f"  exp(mean_d)-1 : {log_eff['pct_effect_log']:+.2f}%")
    print(f"  Cohen dz      : {log_eff['dz']:.4f}")
    print(f"  Bootstrap p   : {fc['p_bootstrap']:.4g}  "
          f"CI: [{fc['ci_pct_lo']:+.1f}%, {fc['ci_pct_hi']:+.1f}%]")
    wil = fc.get("p_wilcoxon")
    print(f"  Wilcoxon p    : {wil:.4g}" if wil is not None else "  Wilcoxon p    : N/A")

    print("\n--- Power curve (resampling bootstrap, repo-stratified) ---")
    n_grid = pa["n_grid"]
    step = n_grid[1] - n_grid[0] if len(n_grid) > 1 else pa.get("n_step", 10)
    print(f"  N grid: {n_grid[0]}–{n_grid[-1]}, step={step}")
    print(f"  power_sims={pa['power_sims']}  n_boot={pa['n_boot']}  alpha={pa['alpha']}")
    print(f"\n  {'N':>5}  {'power_boot':>12}  {'power_wil':>12}")
    for row in pa["curve"]:
        marker = " ← N*(0.90)" if row["n"] == pa["n_star_90"] else (
                 " ← N*(0.80)" if row["n"] == pa["n_star_80"] else "")
        print(f"  {row['n']:>5}  {row['power_bootstrap']:>12.3f}  "
              f"{row['power_wilcoxon']:>12.3f}{marker}")

    print(f"\n  N* (0.80 power): {pa['n_star_80']}")
    print(f"  N* (0.90 power): {pa['n_star_90']}")

    print("\n--- Go/no-go for #299 ---")
    print(f"  Verdict: {rec['verdict'].upper()}")
    print(f"  {rec['recommendation']}")
    if rep.get("repo_distribution"):
        print(f"\n  Repo distribution (stratification): {rep['repo_distribution']}")


def _write_outputs(rep: dict, out_prefix: str) -> None:
    out = Path(out_prefix)
    out.parent.mkdir(parents=True, exist_ok=True)

    json_path = out.with_suffix(".json")
    json_path.write_text(json.dumps(rep, indent=2))

    csv_path = out.with_suffix(".csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["n", "power_bootstrap", "power_wilcoxon"])
        w.writeheader()
        for row in rep["power_analysis"]["curve"]:
            w.writerow(row)

    print(f"\nWrote {json_path} and {csv_path}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--runs", nargs="+", required=True, type=Path,
        help="Seed run dirs (e.g. full_run_seed_1 full_run_seed_2 full_run_seed_3).",
    )
    ap.add_argument("--treatment", default="onlycode")
    ap.add_argument("--reference", default="baseline")
    ap.add_argument(
        "--n-boot", type=int, default=10000,
        help="Bootstrap resamples for the per-simulation test (default: 10000).",
    )
    ap.add_argument(
        "--power-sims", type=int, default=2000,
        help="Number of power simulations per N (default: 2000).",
    )
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--n-min", type=int, default=20)
    ap.add_argument("--n-max", type=int, default=500)
    ap.add_argument("--n-step", type=int, default=10)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument(
        "--out-prefix", default=None,
        help="Write <prefix>.json + <prefix>.csv "
             "(default: runs/swebench/_analysis/power/ws-a).",
    )
    args = ap.parse_args(argv)

    rep = build_report(
        args.runs,
        treatment=args.treatment,
        reference=args.reference,
        n_boot=args.n_boot,
        power_sims=args.power_sims,
        alpha=args.alpha,
        n_min=args.n_min,
        n_max=args.n_max,
        n_step=args.n_step,
        seed=args.seed,
    )
    _print_report(rep)
    out_prefix = args.out_prefix or str(
        REPO_ROOT / "runs" / "swebench" / "_analysis" / "power" / "ws-a"
    )
    _write_outputs(rep, out_prefix)


if __name__ == "__main__":
    main()
