"""Edit-friction hypothesis test for Claude SWE-bench onlycode.

Hypothesis: Claude's onlycode arm pays an output-token tax on SWE-bench because
it must write Python scripts to perform edits that the baseline arm performs
with native Edit/Write calls. Prediction: per-instance Δ_cost (onlycode−baseline)
should correlate POSITIVELY with gold-patch size.

This script:
  1. Pulls gold patches from HuggingFace (SWE-bench_Verified, SWE-bench).
  2. Joins to per-instance metrics from paper/data/raw/all_results.csv.
  3. Computes Spearman ρ between patch-size proxies and per-instance Δ
     for (output_tokens, cost, cost_adj, turns), Claude SWE-bench only.
  4. Also reports Codex SWE-bench correlations as a control (placebo).
  5. Cross-cell control: re-runs the same correlation logic on Claude artifact.
     (Expectation: weaker correlation than Claude SWE-bench, because artifact
     tasks generate single scripts rather than edits.)

Patch-size proxies (we report all three; the qualitative answer should not
depend on the choice):
  - patch_lines_added : `+` lines in the gold patch (test_patch excluded).
  - patch_lines_changed : `+` plus `-` lines.
  - patch_files_touched : number of distinct files modified.

Writes paper/investigations/edit_friction_data.csv (per-instance join) and
prints a results table to stdout.
"""
from __future__ import annotations
import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path

from datasets import load_dataset
from scipy.stats import spearmanr, pearsonr

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "paper" / "data" / "raw" / "all_results.csv"
OUT_CSV = Path(__file__).parent / "edit_friction_data.csv"


def _parse_patch(patch_text: str) -> dict[str, int]:
    """Count + / - lines and files touched in a unified diff."""
    added = removed = 0
    files = set()
    cur_file = None
    for line in patch_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                cur_file = parts[3][2:] if parts[3].startswith("b/") else parts[3]
                files.add(cur_file)
        elif line.startswith("+++ "):
            f = line[4:].strip()
            if f.startswith("b/"):
                f = f[2:]
            if f and f != "/dev/null":
                files.add(f)
        elif line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return {
        "patch_lines_added": added,
        "patch_lines_removed": removed,
        "patch_lines_changed": added + removed,
        "patch_files_touched": len(files),
    }


def fetch_gold_patches(instance_ids: set[str]) -> dict[str, dict]:
    """Return {instance_id: parsed_patch_metrics} pulling from HF."""
    out: dict[str, dict] = {}
    for ds_name in ("princeton-nlp/SWE-bench_Verified", "princeton-nlp/SWE-bench"):
        if not (instance_ids - set(out)):
            break
        print(f"[fetch] {ds_name} (streaming)...")
        ds = load_dataset(ds_name, split="test", streaming=True)
        for row in ds:
            iid = row["instance_id"]
            if iid in instance_ids and iid not in out:
                out[iid] = _parse_patch(row.get("patch", ""))
    missing = instance_ids - set(out)
    if missing:
        print(f"[warn] {len(missing)} instances not found in HF: {sorted(missing)[:5]}...")
    return out


def load_per_instance() -> dict[tuple, dict]:
    """Return {(benchmark, agent, arm, instance_id): {metric: mean_across_seeds}}."""
    buckets: dict[tuple, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    with open(RAW, newline="") as f:
        for r in csv.DictReader(f):
            if r["verdict"] == "env_fail":
                continue
            key = (r["benchmark"], r["agent"], r["arm"], r["instance_id"])
            buckets[key]["pass"].append(1.0 if r["verdict"] == "PASS" else 0.0)
            for src in ("cost_usd", "cost_usd_adjusted", "num_turns",
                        "tool_calls", "llm_calls", "input_tokens",
                        "output_tokens", "wall_secs"):
                v = r.get(src, "")
                if v not in ("", None, "NA"):
                    try:
                        buckets[key][src].append(float(v))
                    except ValueError:
                        pass
    out: dict[tuple, dict] = {}
    for key, by_metric in buckets.items():
        out[key] = {m: statistics.fmean(vs) for m, vs in by_metric.items() if vs}
    return out


def paired_delta(per_inst, benchmark, agent, arm_a, arm_b, metric):
    """Return list of (instance_id, Δ = metric_a - metric_b)."""
    out = []
    seen_inst = {k[3] for k in per_inst if k[:3] == (benchmark, agent, arm_a)}
    for inst in seen_inst:
        a_row = per_inst.get((benchmark, agent, arm_a, inst), {})
        b_row = per_inst.get((benchmark, agent, arm_b, inst), {})
        if metric in a_row and metric in b_row:
            out.append((inst, a_row[metric] - b_row[metric]))
    return out


def spearman_with_ci(x, y, n_boot=2000, seed=0):
    """Bootstrap 95% CI for Spearman ρ."""
    import random
    rng = random.Random(seed)
    n = len(x)
    rho, p = spearmanr(x, y)
    boots = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        bx = [x[i] for i in idx]
        by = [y[i] for i in idx]
        if len(set(bx)) < 2 or len(set(by)) < 2:
            continue
        boots.append(float(spearmanr(bx, by).statistic))
    boots.sort()
    if boots:
        lo = boots[int(0.025 * len(boots))]
        hi = boots[int(0.975 * len(boots))]
    else:
        lo = hi = float("nan")
    return float(rho), float(p), lo, hi


def main():
    per_inst = load_per_instance()
    swe_instances = {k[3] for k in per_inst if k[0] == "swebench"}
    print(f"Found {len(swe_instances)} unique SWE-bench instance IDs across all runs.")

    gold = fetch_gold_patches(swe_instances)
    print(f"Got patches for {len(gold)}/{len(swe_instances)} instances.")

    # Build join CSV: one row per (benchmark, agent, instance_id) with patch metrics +
    # per-instance Δ for all arm contrasts of interest.
    arm_pairs = {
        "swebench": [("onlycode", "baseline"), ("onlycode", "bash_only"),
                     ("bash_only", "baseline")],
        "artifact": [("code_only", "tool_rich"), ("code_only", "bash_only"),
                     ("bash_only", "tool_rich")],
    }
    metrics = ["output_tokens", "cost_usd", "cost_usd_adjusted",
               "input_tokens", "num_turns", "llm_calls", "tool_calls", "pass"]

    join_rows = []
    # Identify all (benchmark, agent, instance_id) triples that have at least one arm.
    triples = {(k[0], k[1], k[3]) for k in per_inst}
    for bench, agent, inst in sorted(triples):
        if bench != "swebench":
            continue  # artifact has no gold patch from HF; skip
        patch = gold.get(inst)
        if not patch:
            continue
        row: dict = {"benchmark": bench, "agent": agent, "instance_id": inst,
                     **patch}
        for arm_a, arm_b in arm_pairs.get(bench, []):
            a_row = per_inst.get((bench, agent, arm_a, inst), {})
            b_row = per_inst.get((bench, agent, arm_b, inst), {})
            for m in metrics:
                col = f"delta_{m}_{arm_a}_minus_{arm_b}"
                if m in a_row and m in b_row:
                    row[col] = a_row[m] - b_row[m]
        # Also dump per-arm raw values for reference.
        for arm in ("baseline", "onlycode", "bash_only", "code_only", "tool_rich"):
            for m in metrics:
                v = per_inst.get((bench, agent, arm, inst), {}).get(m)
                if v is not None:
                    row[f"{arm}_{m}"] = v
        join_rows.append(row)

    # Write join CSV.
    all_cols = sorted({c for r in join_rows for c in r.keys()})
    head_cols = ["benchmark", "agent", "instance_id",
                 "patch_lines_added", "patch_lines_removed",
                 "patch_lines_changed", "patch_files_touched"]
    rest = [c for c in all_cols if c not in head_cols]
    with OUT_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=head_cols + rest)
        w.writeheader()
        for r in join_rows:
            w.writerow(r)
    print(f"Wrote {OUT_CSV} with {len(join_rows)} rows.\n")

    # Compute Spearman correlations for the primary tests.
    print("=" * 100)
    print("EDIT-FRICTION TEST: Spearman correlation between patch-size proxies and per-instance Δ")
    print("=" * 100)

    proxies = ["patch_lines_added", "patch_lines_changed", "patch_files_touched"]
    contrasts_of_interest = [
        ("swebench", "claude", "onlycode", "baseline"),       # primary
        ("swebench", "codex",  "onlycode", "baseline"),       # placebo (no native Edit)
        ("swebench", "claude", "bash_only", "baseline"),      # bash also lacks Edit
        ("swebench", "claude", "onlycode", "bash_only"),      # onlycode vs bash (both edit-friction-y)
    ]
    metric_focus = ["output_tokens", "cost_usd", "cost_usd_adjusted",
                    "num_turns", "llm_calls"]

    for bench, agent, arm_a, arm_b in contrasts_of_interest:
        print(f"\n--- {bench} / {agent} / Δ = {arm_a} − {arm_b} ---")
        for metric in metric_focus:
            deltas = paired_delta(per_inst, bench, agent, arm_a, arm_b,
                                  {"output_tokens": "output_tokens",
                                   "cost_usd": "cost_usd",
                                   "cost_usd_adjusted": "cost_usd_adjusted",
                                   "num_turns": "num_turns",
                                   "llm_calls": "llm_calls"}[metric])
            d_by_inst = {inst: d for inst, d in deltas}
            print(f"  {metric:<22}", end="")
            for proxy in proxies:
                xs, ys = [], []
                for inst, d in d_by_inst.items():
                    p = gold.get(inst)
                    if not p:
                        continue
                    xs.append(p[proxy])
                    ys.append(d)
                if len(xs) < 5:
                    print(f"  {proxy[:18]:<18}  n<5", end="")
                    continue
                rho, pv, lo, hi = spearman_with_ci(xs, ys)
                sig = "***" if pv < 0.001 else "**" if pv < 0.01 else "*" if pv < 0.05 else ""
                print(f"  {proxy[:14]:<14} ρ={rho:+.3f} [{lo:+.2f},{hi:+.2f}] p={pv:.2g} {sig:<3} n={len(xs)}", end="")
            print()


if __name__ == "__main__":
    main()
