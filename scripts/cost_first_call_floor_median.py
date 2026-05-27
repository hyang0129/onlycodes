#!/usr/bin/env python3
"""
First-call cache-floor adjustment for codex runs.

Premise (different from cost_first_call_adjust.py): per-arm batching of codex
runs gives most tasks a warm first-call cache hit (~90% of input cached). A
minority of tasks miss this cache (cold-start outliers due to LRU eviction,
prompt-prefix drift, or chatgpt-edge routing variance). Those cold outliers
are NOT a fair reflection of the steady-state per-arm cost — the typical run
benefits from the warm cache, and the cold tasks would too if re-run.

Methodology:
  1. Per arm, compute the MEDIAN first-billed-call cached_input_tokens over
     tasks that had a non-zero cache hit ("warm subset"). Tasks with first-
     call cached == 0 are EXCLUDED from the median calculation (they're the
     cold outliers we're trying to correct, including them would bias the
     median downward).
  2. For each task, floor the first-call cached at the median (capped at the
     first-call input_tokens — can't cache more than was sent). Cold tasks
     (cached=0) get adjusted UP to median; warm tasks already at/above
     median are unchanged.
  3. Recompute total cost = sum across all calls of
        (input - cached) * input_rate
      + cached         * cached_rate
      + output         * output_rate
     where only the first call's cached value is adjusted.

Inputs:
  Codex rollout files at <result>.rollout.jsonl, which carry per-call
  token_count event_msg records with `info.last_token_usage`. These are
  produced by the post-2026-05-27 harness (--ephemeral removed, rollouts
  preserved). Tasks without rollouts (legacy runs) are skipped.

Layouts supported:
  artifact: <run_dir>/<instance>/<arm>/run<N>/agent.jsonl[.rollout.jsonl]
  swebench: <run_dir>/<instance>_<arm>_run<N>.jsonl[.rollout.jsonl]

Output: per-arm summary with median, n_floored, orig vs adj total cost.

Usage:
  scripts/cost_first_call_floor_median.py <run_dir> [--csv out.csv]
"""

import argparse
import csv
import json
import statistics
import sys
import tomllib
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PRICES_TOML = REPO_ROOT / "swebench" / "codex_prices.toml"


def load_codex_prices() -> dict[str, dict[str, float]]:
    with open(PRICES_TOML, "rb") as f:
        data = tomllib.load(f)
    out = {}
    for _, entry in data.items():
        if isinstance(entry, dict) and "model" in entry:
            out[entry["model"]] = {
                "input": float(entry["input"]),
                "cached_input": float(entry["cached_input"]),
                "output": float(entry["output"]),
            }
    return out


def extract_model(agent_jsonl: Path) -> str | None:
    """Read model from the meta record at the top of an agent jsonl."""
    try:
        with open(agent_jsonl) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") == "meta":
                    return d.get("model") or d.get("codex_model")
                # First non-meta line — stop looking.
                return None
    except OSError:
        return None
    return None


def extract_calls(rollout_path: Path) -> list[dict]:
    """Return per-billed-call usage from a codex rollout file.

    Skips the call0 handshake (info.last_token_usage is None there). Returns
    in chronological order; the first entry IS the first billed API call.
    """
    calls: list[dict] = []
    try:
        with open(rollout_path) as f:
            for line in f:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("type") != "event_msg":
                    continue
                payload = e.get("payload") or {}
                if payload.get("type") != "token_count":
                    continue
                info = payload.get("info") or {}
                lu = info.get("last_token_usage")
                if not lu or not lu.get("input_tokens"):
                    continue
                calls.append({
                    "input": int(lu.get("input_tokens") or 0),
                    "cached": int(lu.get("cached_input_tokens") or 0),
                    "output": int(lu.get("output_tokens") or 0),
                })
    except OSError:
        return []
    return calls


def call_cost(call: dict, rates: dict) -> float:
    inp = call["input"]
    cac = min(call["cached"], inp)
    out = call["output"]
    non_cached = max(0, inp - cac)
    return (
        non_cached * rates["input"]
        + cac * rates["cached_input"]
        + out * rates["output"]
    ) / 1_000_000


def walk_artifact(run_dir: Path):
    for task_dir in sorted(run_dir.iterdir()):
        if not task_dir.is_dir() or task_dir.name.startswith("_"):
            continue
        for arm_dir in sorted(task_dir.iterdir()):
            if not arm_dir.is_dir():
                continue
            for run_subdir in sorted(arm_dir.iterdir()):
                if not run_subdir.is_dir() or not run_subdir.name.startswith("run"):
                    continue
                agent = run_subdir / "agent.jsonl"
                rollout = run_subdir / "agent.jsonl.rollout.jsonl"
                if agent.exists() and rollout.exists():
                    yield task_dir.name, arm_dir.name, run_subdir.name, agent, rollout


def walk_swebench(run_dir: Path):
    for jsonl in sorted(run_dir.glob("*_run*.jsonl")):
        if jsonl.name.endswith(".rollout.jsonl"):
            continue
        rollout = jsonl.with_suffix(".jsonl.rollout.jsonl")
        # Pattern: <instance>_<arm>_run<N>.jsonl
        stem = jsonl.stem
        parts = stem.rsplit("_run", 1)
        if len(parts) != 2:
            continue
        run = "run" + parts[1]
        body = parts[0]
        for arm in ("onlycode", "baseline", "bash_only"):
            suffix = "_" + arm
            if body.endswith(suffix):
                if rollout.exists():
                    yield body[: -len(suffix)], arm, run, jsonl, rollout
                break


def collect(run_dir: Path) -> list[dict]:
    layout = "artifact" if "artifact" in str(run_dir).lower() else "swebench"
    walker = walk_artifact if layout == "artifact" else walk_swebench
    rows = []
    for inst, arm, run, agent, rollout in walker(run_dir):
        calls = extract_calls(rollout)
        if not calls:
            continue
        model = extract_model(agent) or "gpt-5.5"
        rows.append({
            "instance_id": inst,
            "arm": arm,
            "run": run,
            "model": model,
            "calls": calls,
            "rollout": str(rollout),
        })
    return rows


def adjust(rows: list[dict], rates_by_model: dict) -> dict:
    by_arm: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_arm[r["arm"]].append(r)

    detailed = []
    per_arm = {}
    for arm, arm_rows in by_arm.items():
        warm_first_cached = [
            r["calls"][0]["cached"] for r in arm_rows
            if r["calls"][0]["cached"] > 0
        ]
        median_cached = (
            int(statistics.median(warm_first_cached)) if warm_first_cached else 0
        )
        n_warm = len(warm_first_cached)

        orig_sum = adj_sum = 0.0
        n_floored = 0
        moved_total = 0
        for r in arm_rows:
            rates = rates_by_model.get(r["model"])
            if rates is None:
                continue
            calls = r["calls"]
            orig = sum(call_cost(c, rates) for c in calls)

            first = calls[0]
            first_input = first["input"]
            first_cached = first["cached"]
            adj_cached = max(first_cached, min(median_cached, first_input))
            moved = adj_cached - first_cached

            adj_first = dict(first)
            adj_first["cached"] = adj_cached
            adj_calls = [adj_first] + calls[1:]
            adj = sum(call_cost(c, rates) for c in adj_calls)

            if moved > 0:
                n_floored += 1
                moved_total += moved

            detailed.append({
                "instance_id": r["instance_id"],
                "arm": arm,
                "run": r["run"],
                "model": r["model"],
                "n_calls": len(calls),
                "first_input": first_input,
                "first_cached": first_cached,
                "first_cached_adj": adj_cached,
                "moved_tokens": moved,
                "orig_cost": orig,
                "adj_cost": adj,
                "delta_cost": adj - orig,
            })
            orig_sum += orig
            adj_sum += adj

        per_arm[arm] = {
            "n": len(arm_rows),
            "n_warm_first_call": n_warm,
            "median_first_cached": median_cached,
            "n_floored": n_floored,
            "moved_tokens_total": moved_total,
            "orig_total_cost": orig_sum,
            "adj_total_cost": adj_sum,
            "delta_cost": adj_sum - orig_sum,
            "pct_change": (
                100 * (adj_sum - orig_sum) / orig_sum if orig_sum > 0 else 0.0
            ),
        }
    return {"per_row": detailed, "per_arm": per_arm}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--csv", type=Path, default=None)
    args = ap.parse_args()

    if not args.run_dir.is_dir():
        sys.exit(f"not a directory: {args.run_dir}")

    rows = collect(args.run_dir)
    if not rows:
        sys.exit("no rows with rollouts found (legacy runs missing rollouts are skipped)")

    rates_by_model = load_codex_prices()
    result = adjust(rows, rates_by_model)

    print("=" * 96)
    print(f"First-call cache-floor (per-arm median) adjustment — {args.run_dir}")
    print(f"  n_rows={len(rows)}")
    print("=" * 96)
    print(
        f"{'arm':<12} {'n':>4} {'warm_n':>7} {'med_cached':>11} "
        f"{'floored':>8} {'orig $':>10} {'adj $':>10} {'Δ$':>10} {'Δ%':>7}"
    )
    for arm, t in sorted(result["per_arm"].items()):
        print(
            f"{arm:<12} {t['n']:>4} {t['n_warm_first_call']:>7} "
            f"{t['median_first_cached']:>11,} {t['n_floored']:>8} "
            f"{t['orig_total_cost']:>10.4f} {t['adj_total_cost']:>10.4f} "
            f"{t['delta_cost']:>+10.4f} {t['pct_change']:>+6.1f}%"
        )
    print(
        "\n(med_cached: median first-call cached_input over WARM subset (cached>0). "
        "floored: # tasks whose first-call cached was below median and was raised to median. "
        "Δ$ should be negative — flooring raises the cached share, lowers cost.)"
    )

    if args.csv:
        with open(args.csv, "w", newline="") as f:
            fieldnames = list(result["per_row"][0].keys())
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for r in result["per_row"]:
                w.writerow(r)
        print(f"\nWrote {len(result['per_row'])} rows to {args.csv}")


if __name__ == "__main__":
    main()
