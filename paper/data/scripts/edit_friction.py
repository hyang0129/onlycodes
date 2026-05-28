"""Edit-friction headline numbers for §6 mechanism question 1.

Produces paper/data/edit_friction.csv with the cells cited by the §6 paragraph.
Reads:
  - paper/data/raw/all_results.csv      (per-run metrics)
  - paper/data/swe_gold_patch_sizes.csv (static, committed; sourced from HF once)
  - runs/swebench/<set>/*.jsonl         (Claude logs; for edit_chars proxy)

Outputs one CSV row per (metric) cell. See edit_friction.csv schema below.

Mechanism: for each Claude SWE-bench instance, compute the agent's "edit
volume" — total characters typed into Write/Edit/MultiEdit/execute_code/Bash
tool-use blocks across all seeds, averaged. Compare per-instance Δ_edit_chars
(onlycode − baseline) against Δ_output_tokens. Spearman ρ is the headline.

Investigation provenance: paper/investigations/edit_friction_findings.md
(2026-05-28 review pass).
"""
from __future__ import annotations
import csv
import datetime
import json
import math
import statistics
import subprocess
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import mannwhitneyu, spearmanr

REPO = Path(__file__).resolve().parents[3]
RAW = REPO / "paper" / "data" / "raw" / "all_results.csv"
GOLD = REPO / "paper" / "data" / "raw" / "swe_gold_patch_sizes.csv"
OUT = REPO / "paper" / "data" / "edit_friction.csv"
THIS_SCRIPT = Path(__file__).relative_to(REPO)


def _load_gold_patches() -> dict[str, dict[str, int]]:
    out = {}
    with GOLD.open() as f:
        for line in f:
            if line.startswith("#"):
                continue
            reader = csv.DictReader([line] + list(f))
            for r in reader:
                out[r["instance_id"]] = {
                    "patch_lines_added": int(r["patch_lines_added"]),
                    "patch_lines_changed": int(r["patch_lines_changed"]),
                    "patch_files_touched": int(r["patch_files_touched"]),
                }
            break
    return out


def _count_edit_chars(log_path: Path) -> int:
    """Sum character counts of Write/Edit/MultiEdit/execute_code/Bash tool_use blocks."""
    total = 0
    if not log_path.exists():
        return 0
    try:
        with log_path.open() as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = r.get("message") or r
                content = msg.get("content") if isinstance(msg, dict) else None
                if not isinstance(content, list):
                    continue
                for blk in content:
                    if not isinstance(blk, dict) or blk.get("type") != "tool_use":
                        continue
                    name = blk.get("name", "")
                    inp = blk.get("input", {}) or {}
                    if name == "Write":
                        total += len(str(inp.get("content", "")))
                    elif name == "Edit":
                        total += len(str(inp.get("new_string", "")))
                    elif name == "MultiEdit":
                        for e in inp.get("edits", []):
                            total += len(str(e.get("new_string", "")))
                    elif name in ("mcp__codebox__execute_code", "execute_code"):
                        total += len(str(inp.get("code", "")))
                    elif name == "Bash":
                        total += len(str(inp.get("command", "")))
    except OSError:
        return 0
    return total


def _per_instance_arm_means() -> tuple[dict, dict]:
    """Returns (output_tokens, edit_chars) keyed by (arm, instance_id) → mean across seeds.

    Only Claude SWE-bench rows; env_fail excluded.
    """
    out_tok: dict[tuple[str, str], list[float]] = defaultdict(list)
    edit_ch: dict[tuple[str, str], list[int]] = defaultdict(list)
    with RAW.open() as f:
        for r in csv.DictReader(f):
            if r["benchmark"] != "swebench" or r["agent"] != "claude":
                continue
            if r["verdict"] == "env_fail":
                continue
            key = (r["arm"], r["instance_id"])
            try:
                out_tok[key].append(float(r["output_tokens"]))
            except (ValueError, KeyError):
                pass
            log_path = REPO / r["result_path"]
            edit_ch[key].append(_count_edit_chars(log_path))
    out_tok_mean = {k: statistics.fmean(vs) for k, vs in out_tok.items() if vs}
    edit_ch_mean = {k: statistics.fmean(vs) for k, vs in edit_ch.items() if vs}
    return out_tok_mean, edit_ch_mean


def _theil_sen(x, y) -> float:
    x = np.asarray(x, float); y = np.asarray(y, float)
    n = len(x)
    if n < 3:
        return float("nan")
    slopes = []
    for i in range(n):
        for j in range(i + 1, n):
            if x[j] != x[i]:
                slopes.append((y[j] - y[i]) / (x[j] - x[i]))
    if not slopes:
        return float("nan")
    return float(np.median(slopes))


def _ols_intercept(x, y) -> tuple[float, float]:
    x = np.asarray(x, float); y = np.asarray(y, float)
    if len(x) < 3 or x.std() == 0:
        return float("nan"), float("nan")
    slope, intercept = np.polyfit(x, y, 1)
    return float(slope), float(intercept)


def main():
    gold = _load_gold_patches()
    out_tok, edit_ch = _per_instance_arm_means()

    # Build per-instance Δ vectors (Claude SWE-bench, onlycode − baseline).
    instances = sorted({iid for (_arm, iid) in out_tok})
    delta_edit_chars = []
    delta_out_tokens = []
    out_baseline = []
    out_onlycode = []
    patch_lines_added = []
    for iid in instances:
        o = out_tok.get(("onlycode", iid))
        b = out_tok.get(("baseline", iid))
        eo = edit_ch.get(("onlycode", iid))
        eb = edit_ch.get(("baseline", iid))
        pa = gold.get(iid, {}).get("patch_lines_added")
        if None in (o, b, eo, eb, pa):
            continue
        delta_edit_chars.append(eo - eb)
        delta_out_tokens.append(o - b)
        out_baseline.append(b)
        out_onlycode.append(o)
        patch_lines_added.append(pa)

    n = len(delta_edit_chars)

    # Headline: ρ(Δ_edit_chars, Δ_output_tokens).
    rho_edit, p_edit = spearmanr(delta_edit_chars, delta_out_tokens)

    # Reference: ρ(gold patch_lines_added, Δ_output_tokens).
    rho_gold, p_gold = spearmanr(patch_lines_added, delta_out_tokens)

    # Median-split on patch_lines_added.
    median_pa = statistics.median(patch_lines_added)
    low_d = [d for pa, d in zip(patch_lines_added, delta_out_tokens) if pa <= median_pa]
    high_d = [d for pa, d in zip(patch_lines_added, delta_out_tokens) if pa > median_pa]
    mean_low = statistics.fmean(low_d) if low_d else float("nan")
    mean_high = statistics.fmean(high_d) if high_d else float("nan")
    highpatch_ratio = mean_high / mean_low if mean_low > 0 else float("nan")
    mw_p = float(mannwhitneyu(high_d, low_d, alternative="greater").pvalue) if (low_d and high_d) else float("nan")

    # Theil-Sen slope on output_tokens vs patch_lines_added, per arm; report Δ.
    ts_baseline = _theil_sen(patch_lines_added, out_baseline)
    ts_onlycode = _theil_sen(patch_lines_added, out_onlycode)
    ts_slope_diff = ts_onlycode - ts_baseline

    # OLS intercept gap (fixed-cost verbosity component, at zero patch size).
    _, int_base = _ols_intercept(patch_lines_added, out_baseline)
    _, int_only = _ols_intercept(patch_lines_added, out_onlycode)
    intercept_gap = int_only - int_base

    sha = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip() or "unknown"
    ts = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    rows = [
        ("n_instances", n, 0),
        ("rho_edit_chars", rho_edit, 3),
        ("rho_edit_chars_p", p_edit, 4),
        ("rho_gold_lines", rho_gold, 3),
        ("rho_gold_lines_p", p_gold, 4),
        ("median_patch_lines_added", median_pa, 0),
        ("lowpatch_delta_output_tokens", mean_low, 0),
        ("highpatch_delta_output_tokens", mean_high, 0),
        ("highpatch_ratio", highpatch_ratio, 2),
        ("highpatch_mw_p", mw_p, 4),
        ("theilsen_slope_baseline", ts_baseline, 1),
        ("theilsen_slope_onlycode", ts_onlycode, 1),
        ("theilsen_slope_diff", ts_slope_diff, 1),
        ("intercept_baseline", int_base, 0),
        ("intercept_onlycode", int_only, 0),
        ("intercept_gap", intercept_gap, 0),
    ]

    with OUT.open("w", newline="") as f:
        f.write(f"# source_commit: {sha}\n")
        f.write(f"# generated: {ts}\n")
        f.write(f"# generator: {THIS_SCRIPT}\n")
        f.write(f"# key_schema: metric\n")
        f.write(f"# default_precision: 3\n")
        f.write(f"# Headline edit-friction numbers for §6 Q1. Claude SWE-bench, Δ = onlycode − baseline, n=100.\n")
        f.write(f"# rho_edit_chars: Spearman ρ of (per-instance Δ_edit_chars, Δ_output_tokens). Headline test.\n")
        f.write(f"# rho_gold_lines: ρ of (gold patch_lines_added, Δ_output_tokens). Reference / weaker proxy.\n")
        f.write(f"# highpatch_ratio: mean_high / mean_low of Δ_output_tokens, split on median gold patch_lines_added.\n")
        f.write(f"# theilsen_slope_*: robust median slope of output_tokens vs patch_lines_added, per arm.\n")
        f.write(f"# intercept_*: OLS intercept of output_tokens vs patch_lines_added — fixed-cost component at zero patch size.\n")
        w = csv.writer(f)
        w.writerow(["metric", "value", "precision"])
        for metric, value, prec in rows:
            if isinstance(value, float) and math.isnan(value):
                w.writerow([metric, "", prec])
            else:
                w.writerow([metric, value, prec])

    print(f"Wrote {OUT} with {len(rows)} rows. n={n} instances.")
    print(f"  rho_edit_chars  = {rho_edit:+.3f} (p={p_edit:.3g})")
    print(f"  highpatch_ratio = {highpatch_ratio:.2f}x  (low={mean_low:.0f}, high={mean_high:.0f}, MW p={mw_p:.3g})")
    print(f"  theilsen_slope_diff (onlycode − baseline) = {ts_slope_diff:+.1f} tok/line")
    print(f"  intercept_gap   = {intercept_gap:+.0f} tokens")


if __name__ == "__main__":
    main()
