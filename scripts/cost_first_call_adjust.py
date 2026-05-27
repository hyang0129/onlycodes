#!/usr/bin/env python3
"""
First-call cache adjustment for agent runs (codex OR claude).

Premise: the very first API call of each task should not benefit from a warm
prompt cache — any cache reads on call 1 reflect *cross-task* contamination
(a prior task's shared prefix), not legitimate within-task reuse. We
re-classify those tokens as full-rate input.

Two schemas, two paths:

  CODEX (``turn.completed.usage`` is aggregate-only per task):
    Estimate per-arm shared_prefix_size = MIN(cached_input_tokens > 0).
    Subtract from each task's cached_input, recharge at full input rate.
    EMPIRICAL NOTE (2026-05-26 mitm captures, 30/30 codex code_only sessions):
    codex with ChatGPT login starts each task with prompt_cache_key fresh,
    so call 1 is reliably COLD (cached_tokens=0) and this adjustment is a
    near-no-op in practice. We still run it for completeness; treat the
    adjusted column as an upper bound.

  CLAUDE (each ``assistant`` event carries the API call's ``message.usage``):
    Walk ``assistant`` events, deduplicate by ``message.id`` (the same id can
    appear across multiple stream-delta events with identical cumulative
    usage). The first unique message's ``cache_read_input_tokens`` IS the
    cross-task contamination — no estimation needed. Recharge at full input.

Output: per-arm orig vs adjusted total cost, delta, and per-task detail.

Usage:
  scripts/cost_first_call_adjust.py <run_dir>
      [--mode auto|codex|claude]
      [--sample N]
      [--instances inst1,inst2,...]
      [--csv out.csv]
      [--shared-prefix N]  # codex only
"""

import argparse
import csv
import json
import sys
import tomllib
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PRICES_TOML = REPO_ROOT / "swebench" / "codex_prices.toml"

# Claude pricing (USD per 1M tokens). Hardcoded here because the existing
# harness uses Anthropic's authoritative `total_cost_usd` from the JSONL and
# never needed a local rate table. Sources cross-checked 2026-05-26:
#   - https://docs.claude.com/en/docs/about-claude/pricing
#   - https://docs.claude.com/en/docs/build-with-claude/prompt-caching
# Standard tier, claude-sonnet-4-6, 5-minute ephemeral cache.
CLAUDE_RATES = {
    "claude-sonnet-4-6": {
        "input": 3.00,
        "cache_creation_5m": 3.75,   # 1.25× input
        "cache_creation_1h": 6.00,   # 2.0× input
        "cache_read": 0.30,          # 0.1× input
        "output": 15.00,
    },
}


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


# ---------------------------------------------------------------------------
# Codex path (aggregate-only)
# ---------------------------------------------------------------------------


def codex_extract_task(jsonl_path: Path) -> tuple[dict | None, str | None]:
    """Return (aggregate_usage_dict, model) for one codex task JSONL."""
    model = None
    usage = None
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = d.get("type")
            if t == "meta":
                model = d.get("model") or d.get("codex_model")
            elif t == "turn.completed" and "usage" in d:
                usage = d["usage"]
    if not usage:
        return None, None
    return usage, model


def codex_cost(usage: dict, rates: dict) -> float:
    inp = int(usage.get("input_tokens", 0))
    cac = int(usage.get("cached_input_tokens", 0))
    out = int(usage.get("output_tokens", 0))  # already includes reasoning
    non_cached = max(0, inp - cac)
    return (
        non_cached * rates["input"]
        + cac * rates["cached_input"]
        + out * rates["output"]
    ) / 1_000_000


def codex_estimate_prefix(cached_values: list[int]) -> int:
    nz = [c for c in cached_values if c > 0]
    return min(nz) if nz else 0


def codex_adjust(rows: list[dict], rates_by_model: dict, override_prefix: int | None) -> dict:
    by_arm = defaultdict(list)
    for r in rows:
        by_arm[r["arm"]].append(r)

    detailed = []
    per_arm = {}
    for arm, arm_rows in by_arm.items():
        cached_vals = [int(r["usage"].get("cached_input_tokens", 0)) for r in arm_rows]
        prefix = override_prefix if override_prefix is not None else codex_estimate_prefix(cached_vals)

        orig_sum = adj_sum = 0.0
        moved_total = 0
        for r in arm_rows:
            u = r["usage"]
            model = r["model"] or "gpt-5.5"
            rates = rates_by_model.get(model)
            if rates is None:
                continue
            cached_t = int(u.get("cached_input_tokens", 0))
            orig = codex_cost(u, rates)
            moved = min(cached_t, prefix)
            delta = moved * (rates["input"] - rates["cached_input"]) / 1_000_000
            adj = orig + delta
            detailed.append({
                **r,
                "input_tokens": int(u.get("input_tokens", 0)),
                "cached_input_tokens": cached_t,
                "output_tokens": int(u.get("output_tokens", 0)),
                "first_call_cache_read": None,  # not directly measurable for codex
                "moved_tokens": moved,
                "shared_prefix": prefix,
                "orig_cost": orig,
                "adj_cost": adj,
                "delta_cost": delta,
            })
            orig_sum += orig
            adj_sum += adj
            moved_total += moved

        per_arm[arm] = {
            "n": len(arm_rows),
            "estimator": "MIN-nonzero" if override_prefix is None else "override",
            "shared_prefix_tokens": prefix,
            "orig_total_cost": orig_sum,
            "adj_total_cost": adj_sum,
            "delta_cost": adj_sum - orig_sum,
            "pct_increase": 100 * (adj_sum - orig_sum) / orig_sum if orig_sum > 0 else 0.0,
            "moved_tokens_total": moved_total,
        }
    return {"per_row": detailed, "per_arm": per_arm}


# ---------------------------------------------------------------------------
# Claude path (per-call from assistant events)
# ---------------------------------------------------------------------------


def claude_extract_task(jsonl_path: Path) -> tuple[list[dict], dict | None, str | None, float | None]:
    """
    Return (per_call_usages, aggregate_usage, model, orig_total_cost_usd).
    per_call_usages: ordered list of unique-by-message-id usage dicts.
    """
    seen_ids: set[str] = set()
    per_call: list[dict] = []
    aggregate = None
    cost = None
    model = None
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = d.get("type")
            if t == "assistant":
                msg = d.get("message", {})
                msg_id = msg.get("id")
                u = msg.get("usage")
                if not isinstance(u, dict):
                    continue
                # Deduplicate: stream emits the same id across multiple delta
                # events; usage on each is cumulative for that message.
                if msg_id and msg_id in seen_ids:
                    continue
                seen_ids.add(msg_id or f"_pos_{len(per_call)}")
                per_call.append(u)
                if not model:
                    model = msg.get("model")
            elif t == "result":
                cost = d.get("total_cost_usd")
                aggregate = d.get("usage")
    return per_call, aggregate, model, cost


def claude_adjust(rows: list[dict], rates_by_model: dict) -> dict:
    by_arm = defaultdict(list)
    for r in rows:
        by_arm[r["arm"]].append(r)

    detailed = []
    per_arm = {}
    for arm, arm_rows in by_arm.items():
        orig_sum = adj_sum = 0.0
        moved_total = 0
        first_call_cache_reads = []
        for r in arm_rows:
            calls = r["per_call"]
            model = r.get("model") or "claude-sonnet-4-6"
            rates = rates_by_model.get(model) or rates_by_model.get("claude-sonnet-4-6")
            orig = r.get("orig_cost") or 0.0  # authoritative from result event
            if not calls:
                continue
            first = calls[0]
            first_cache_read = int(first.get("cache_read_input_tokens", 0))
            first_call_cache_reads.append(first_cache_read)
            delta = first_cache_read * (rates["input"] - rates["cache_read"]) / 1_000_000
            adj = orig + delta
            detailed.append({
                **{k: v for k, v in r.items() if k != "per_call"},
                "n_calls": len(calls),
                "first_call_cache_read": first_cache_read,
                "first_call_cache_creation": int(first.get("cache_creation_input_tokens", 0)),
                "first_call_input_tokens": int(first.get("input_tokens", 0)),
                "moved_tokens": first_cache_read,
                "orig_cost": orig,
                "adj_cost": adj,
                "delta_cost": delta,
            })
            orig_sum += orig
            adj_sum += adj
            moved_total += first_cache_read

        per_arm[arm] = {
            "n": len(arm_rows),
            "median_first_call_cache_read": (
                sorted(first_call_cache_reads)[len(first_call_cache_reads)//2]
                if first_call_cache_reads else 0
            ),
            "n_cold_first_call": sum(1 for c in first_call_cache_reads if c == 0),
            "orig_total_cost": orig_sum,
            "adj_total_cost": adj_sum,
            "delta_cost": adj_sum - orig_sum,
            "pct_increase": 100 * (adj_sum - orig_sum) / orig_sum if orig_sum > 0 else 0.0,
            "moved_tokens_total": moved_total,
        }
    return {"per_row": detailed, "per_arm": per_arm}


# ---------------------------------------------------------------------------
# Layout walkers
# ---------------------------------------------------------------------------


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
                jsonl = run_subdir / "agent.jsonl"
                if jsonl.exists():
                    yield task_dir.name, arm_dir.name, run_subdir.name, jsonl


def walk_swebench(run_dir: Path):
    for jsonl in sorted(run_dir.glob("*_run*.jsonl")):
        if "_backup" in str(jsonl) or "_legacy" in str(jsonl):
            continue
        stem = jsonl.stem
        parts = stem.rsplit("_run", 1)
        if len(parts) != 2:
            continue
        run = "run" + parts[1]
        body = parts[0]
        for arm in ("onlycode", "baseline", "bash_only"):
            suffix = "_" + arm
            if body.endswith(suffix):
                yield body[: -len(suffix)], arm, run, jsonl
                break


def collect(run_dir: Path, mode: str) -> tuple[list[dict], str]:
    layout = "artifact" if "artifact" in str(run_dir).lower() else "swebench"
    walker = walk_artifact if layout == "artifact" else walk_swebench

    if mode == "codex":
        agent = "codex"
    elif mode == "claude":
        agent = "claude"
    else:
        agent = None
        for _, _, _, jsonl in walker(run_dir):
            with open(jsonl) as f:
                head = "".join(f.readline() for _ in range(50))
            if '"turn.completed"' in head and '"cached_input_tokens"' in head:
                agent = "codex"
            elif '"assistant"' in head and '"cache_read_input_tokens"' in head:
                agent = "claude"
            if agent:
                break
        if not agent:
            sys.exit(f"Could not auto-detect agent schema in {run_dir}")

    rows = []
    for inst, arm, run, jsonl in walker(run_dir):
        if agent == "codex":
            usage, model = codex_extract_task(jsonl)
            if not usage:
                continue
            rows.append({
                "instance_id": inst,
                "arm": arm,
                "run": run,
                "model": model,
                "usage": usage,
                "path": str(jsonl),
            })
        else:
            per_call, agg, model, cost = claude_extract_task(jsonl)
            if not per_call:
                continue
            rows.append({
                "instance_id": inst,
                "arm": arm,
                "run": run,
                "model": model,
                "aggregate_usage": agg,
                "per_call": per_call,
                "orig_cost": cost,
                "path": str(jsonl),
            })
    return rows, agent


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--mode", choices=["auto", "codex", "claude"], default="auto")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--instances", type=str, default=None)
    ap.add_argument("--csv", type=Path, default=None)
    ap.add_argument("--shared-prefix", type=int, default=None,
                    help="Codex only: override shared prefix tokens.")
    args = ap.parse_args()

    rows, agent = collect(args.run_dir, args.mode)
    if args.instances:
        keep = set(args.instances.split(","))
        rows = [r for r in rows if r["instance_id"] in keep]
    if not rows:
        sys.exit("No rows after filter")

    codex_rates = load_codex_prices()
    if agent == "codex":
        result = codex_adjust(rows, codex_rates, override_prefix=args.shared_prefix)
    else:
        result = claude_adjust(rows, CLAUDE_RATES)

    print("=" * 96)
    print(f"First-call cache adjustment — {args.run_dir}")
    print(f"  agent={agent}  n_rows={len(rows)}"
          f"{'  instances=' + args.instances if args.instances else ''}")
    print("=" * 96)

    if agent == "codex":
        print(f"{'arm':<12} {'n':>4} {'pfx_tok':>9} {'orig $':>9} {'adj $':>9} {'Δ$':>8} {'Δ%':>6}")
        for arm, t in sorted(result["per_arm"].items()):
            print(
                f"{arm:<12} {t['n']:>4} {t['shared_prefix_tokens']:>9,} "
                f"{t['orig_total_cost']:>9.4f} {t['adj_total_cost']:>9.4f} "
                f"{t['delta_cost']:>+8.4f} {t['pct_increase']:>+5.1f}%"
            )
        print("\n(shared_prefix estimator = MIN-nonzero cached_input. "
              "Codex mitm captures show call 1 is empirically cold; this "
              "adjustment over-corrects — interpret as upper bound.)")
    else:
        print(f"{'arm':<12} {'n':>4} {'med_1st_cr':>11} {'cold':>5} {'orig $':>9} {'adj $':>9} {'Δ$':>8} {'Δ%':>6}")
        for arm, t in sorted(result["per_arm"].items()):
            print(
                f"{arm:<12} {t['n']:>4} {t['median_first_call_cache_read']:>11,} "
                f"{t['n_cold_first_call']:>5} "
                f"{t['orig_total_cost']:>9.4f} {t['adj_total_cost']:>9.4f} "
                f"{t['delta_cost']:>+8.4f} {t['pct_increase']:>+5.1f}%"
            )
        print("\n(med_1st_cr = median first-call cache_read_input_tokens; "
              "cold = how many tasks had first-call cache_read == 0. "
              "adj = orig + first_call_cr × (input_rate − cache_read_rate).)")

    if args.sample > 0:
        per_arm_rows = defaultdict(list)
        for r in result["per_row"]:
            per_arm_rows[r["arm"]].append(r)
        for arm in sorted(per_arm_rows):
            print(f"\n--- {arm}: first {args.sample} tasks ---")
            if agent == "codex":
                print(f"{'instance':<48} {'cached':>9} {'moved':>8} {'orig$':>8} {'adj$':>8} {'Δ$':>8}")
                for r in per_arm_rows[arm][: args.sample]:
                    print(
                        f"{r['instance_id'][:48]:<48} "
                        f"{r['cached_input_tokens']:>9,} {r['moved_tokens']:>8,} "
                        f"{r['orig_cost']:>8.4f} {r['adj_cost']:>8.4f} "
                        f"{r['delta_cost']:>+8.4f}"
                    )
            else:
                print(f"{'instance':<48} {'#calls':>6} {'1st_cr':>9} {'orig$':>8} {'adj$':>8} {'Δ$':>8}")
                for r in per_arm_rows[arm][: args.sample]:
                    print(
                        f"{r['instance_id'][:48]:<48} "
                        f"{r['n_calls']:>6} {r['first_call_cache_read']:>9,} "
                        f"{r['orig_cost']:>8.4f} {r['adj_cost']:>8.4f} "
                        f"{r['delta_cost']:>+8.4f}"
                    )

    if args.csv:
        with open(args.csv, "w", newline="") as f:
            all_keys = set()
            for r in result["per_row"]:
                all_keys.update(r.keys())
            fieldnames = [k for k in (
                "instance_id", "arm", "run", "model", "n_calls",
                "input_tokens", "cached_input_tokens", "output_tokens",
                "first_call_cache_read", "first_call_cache_creation",
                "first_call_input_tokens", "moved_tokens", "shared_prefix",
                "orig_cost", "adj_cost", "delta_cost",
            ) if k in all_keys]
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            for r in result["per_row"]:
                w.writerow(r)
        print(f"\nWrote {len(result['per_row'])} rows to {args.csv}")


if __name__ == "__main__":
    main()
