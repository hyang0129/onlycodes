"""Edit-friction follow-ups (addressing opus-reviewer gaps).

  B1. Both-pass / both-fail subset. The "+19 tok/line" slope may be
      driven by failed runs (debug-loop verbosity), not edit verbosity.
      Re-run within-arm slopes on the both-PASS subset and the both-FAIL
      subset separately. If the slope difference disappears on both-pass,
      the headline edit-friction reading is challenged.

  S1. Robust slope (Theil-Sen) + leverage-drop sensitivity. OLS on a
      heavy-tailed x with R²≈0.01 is fragile. Re-report slopes after
      (a) dropping the top-1 patch outlier, (b) using Theil-Sen median slope.

  S2. BH (Benjamini-Hochberg) correction for the primary Spearman table
      (Claude SWE-bench, Δ = onlycode − baseline, 5 metrics × 3 proxies = 15 tests).

  M3. Agent's actual patch size, parsed from the per-instance JSONL logs
      (files written / lines changed under merged/), correlated against
      output_tokens. This is closer to "how much typing the model actually did"
      than the gold patch.

Reads paper/investigations/edit_friction_data.csv. For M3 also reads
the JSONL logs referenced from paper/data/raw/all_results.csv.
"""
from __future__ import annotations
import csv, json, re, statistics
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

REPO = Path(__file__).resolve().parents[2]
DATA = Path(__file__).parent / "edit_friction_data.csv"
RAW = REPO / "paper" / "data" / "raw" / "all_results.csv"


def load_rows():
    rows = []
    with open(DATA) as f:
        for r in csv.DictReader(f):
            for k, v in list(r.items()):
                if k in ("benchmark", "agent", "instance_id"):
                    continue
                if v in ("", None):
                    r[k] = None
                else:
                    try: r[k] = float(v)
                    except: r[k] = None
            rows.append(r)
    return rows


def ols_slope(x, y):
    x = np.asarray(x, float); y = np.asarray(y, float)
    if len(x) < 3 or x.std() == 0:
        return float("nan")
    slope, _ = np.polyfit(x, y, 1)
    return float(slope)


def theil_sen(x, y):
    """Theil-Sen median slope."""
    x = np.asarray(x, float); y = np.asarray(y, float)
    n = len(x)
    if n < 3:
        return float("nan")
    # All pairwise slopes
    slopes = []
    for i in range(n):
        for j in range(i + 1, n):
            if x[j] != x[i]:
                slopes.append((y[j] - y[i]) / (x[j] - x[i]))
    if not slopes:
        return float("nan")
    return float(np.median(slopes))


def bh_correct(pvalues, alpha=0.05):
    """Benjamini-Hochberg. Return (adjusted_p, rejected)."""
    p = np.asarray(pvalues, float)
    n = len(p)
    order = np.argsort(p)
    ranked_p = p[order]
    adj = np.empty(n)
    cmin = 1.0
    for i in range(n - 1, -1, -1):
        v = ranked_p[i] * n / (i + 1)
        cmin = min(cmin, v)
        adj[i] = cmin
    out = np.empty(n)
    out[order] = adj
    return out, out < alpha


def claude_swe(rows):
    return [r for r in rows if r["agent"] == "claude" and r["benchmark"] == "swebench"]


def main():
    rows = load_rows()
    csub = claude_swe(rows)
    print(f"Claude SWE-bench: {len(csub)} instances\n")

    # ---------- B1: both-pass / both-fail subsets ----------
    print("=" * 100)
    print("(B1) BOTH-PASS / BOTH-FAIL SUBSET SLOPE TEST")
    print("=" * 100)
    print("    Predicting per-arm output_tokens from gold-patch lines_added, restricted to instances")
    print("    where the indicated subset of arms agree on verdict (PASS or FAIL).")

    # Use baseline_pass and onlycode_pass (per-instance, may be 0/0.33/0.67/1
    # across seeds but here we have 1 seed so it's 0/1).
    def slopes_on_subset(sub_rows, label):
        xs, yb, yo, ybash = [], [], [], []
        for r in sub_rows:
            x = r["patch_lines_added"]
            if (r.get("baseline_output_tokens") is not None
                and r.get("onlycode_output_tokens") is not None
                and r.get("bash_only_output_tokens") is not None):
                xs.append(x)
                yb.append(r["baseline_output_tokens"])
                yo.append(r["onlycode_output_tokens"])
                ybash.append(r["bash_only_output_tokens"])
        if len(xs) < 5:
            print(f"  {label} subset: n={len(xs)} too small")
            return
        s_b, s_o, s_ba = ols_slope(xs, yb), ols_slope(xs, yo), ols_slope(xs, ybash)
        ts_b, ts_o, ts_ba = theil_sen(xs, yb), theil_sen(xs, yo), theil_sen(xs, ybash)
        # Mean per-arm output_tokens on this subset
        mb, mo, mba = statistics.fmean(yb), statistics.fmean(yo), statistics.fmean(ybash)
        print(f"\n  {label}  n={len(xs)}")
        print(f"    mean output_tokens  baseline={mb:7.0f}  onlycode={mo:7.0f}  bash_only={mba:7.0f}")
        print(f"    OLS slope (tok/line)  baseline={s_b:+7.2f}  onlycode={s_o:+7.2f}  bash_only={s_ba:+7.2f}")
        print(f"    Theil-Sen slope        baseline={ts_b:+7.2f}  onlycode={ts_o:+7.2f}  bash_only={ts_ba:+7.2f}")
        print(f"    OLS Δ slope (onlycode − baseline) = {s_o - s_b:+7.2f} tok/line")
        print(f"    Theil-Sen Δ slope (onlycode − baseline) = {ts_o - ts_b:+7.2f} tok/line")

    both_pass = [r for r in csub
                 if r.get("baseline_pass") == 1.0 and r.get("onlycode_pass") == 1.0]
    both_fail = [r for r in csub
                 if r.get("baseline_pass") == 0.0 and r.get("onlycode_pass") == 0.0]
    only_onlycode_fail = [r for r in csub
                          if r.get("baseline_pass") == 1.0 and r.get("onlycode_pass") == 0.0]
    only_baseline_fail = [r for r in csub
                          if r.get("baseline_pass") == 0.0 and r.get("onlycode_pass") == 1.0]
    print(f"\n  Verdict breakdown: both_pass={len(both_pass)}  both_fail={len(both_fail)}  "
          f"only_onlycode_fail={len(only_onlycode_fail)}  only_baseline_fail={len(only_baseline_fail)}")

    slopes_on_subset(csub, "ALL instances")
    slopes_on_subset(both_pass, "BOTH PASS")
    slopes_on_subset(both_fail, "BOTH FAIL")

    # ---------- S1: leverage / Theil-Sen sensitivity ----------
    print("\n" + "=" * 100)
    print("(S1) LEVERAGE-DROP + THEIL-SEN SENSITIVITY (all instances, Claude SWE-bench)")
    print("=" * 100)

    # Drop top-1, top-3, top-5 by patch_lines_added
    sorted_rows = sorted(csub, key=lambda r: r["patch_lines_added"] or 0)
    for n_drop in (0, 1, 3, 5, 10):
        sub = sorted_rows[:len(sorted_rows) - n_drop] if n_drop else sorted_rows
        xs = [r["patch_lines_added"] for r in sub]
        yb = [r["baseline_output_tokens"] for r in sub]
        yo = [r["onlycode_output_tokens"] for r in sub]
        s_b, s_o = ols_slope(xs, yb), ols_slope(xs, yo)
        ts_b, ts_o = theil_sen(xs, yb), theil_sen(xs, yo)
        xmax = max(xs)
        print(f"  drop top-{n_drop:<2}  n={len(sub):3}  max_x={xmax:>4}  OLS slopes  base={s_b:+7.2f} only={s_o:+7.2f}  Δ={s_o - s_b:+7.2f}    "
              f"Theil-Sen  base={ts_b:+5.2f} only={ts_o:+5.2f}  Δ={ts_o - ts_b:+5.2f}")

    # ---------- S2: BH correction for the primary Spearman table ----------
    print("\n" + "=" * 100)
    print("(S2) BH (Benjamini-Hochberg) CORRECTION FOR PRIMARY SPEARMAN TABLE")
    print("=" * 100)
    print("    Claude SWE-bench, Δ = onlycode − baseline, n=100, FDR=0.05")

    proxies = ["patch_lines_added", "patch_lines_changed", "patch_files_touched"]
    metrics = [
        ("delta_output_tokens_onlycode_minus_baseline", "output_tokens"),
        ("delta_cost_usd_onlycode_minus_baseline", "cost_usd"),
        ("delta_cost_usd_adjusted_onlycode_minus_baseline", "cost_usd_adjusted"),
        ("delta_num_turns_onlycode_minus_baseline", "num_turns"),
        ("delta_llm_calls_onlycode_minus_baseline", "llm_calls"),
    ]
    tests = []
    for proxy in proxies:
        for delta_col, mname in metrics:
            xs, ys = [], []
            for r in csub:
                if r.get(proxy) is not None and r.get(delta_col) is not None:
                    xs.append(r[proxy]); ys.append(r[delta_col])
            if len(xs) < 5:
                continue
            rho, p = spearmanr(xs, ys)
            tests.append((mname, proxy, float(rho), float(p), len(xs)))

    pvals = [t[3] for t in tests]
    adj, sig = bh_correct(pvals, alpha=0.05)
    print(f"  {'metric':<22} {'proxy':<22} {'n':>4} {'rho':>8} {'p_raw':>10} {'p_BH':>10} sig?")
    for (mname, proxy, rho, p, n), pa, s in zip(tests, adj, sig):
        mark = "*" if s else " "
        print(f"  {mname:<22} {proxy:<22} {n:>4} {rho:>+8.3f} {p:>10.4g} {pa:>10.4g}  {mark}")
    print(f"\n  Of {len(tests)} tests, {int(sig.sum())} survive BH @ FDR 0.05.")

    # ---------- M3: Agent's actual patch size from JSONL ----------
    print("\n" + "=" * 100)
    print("(M3) AGENT-ACTUAL EDIT SIZE FROM JSONL LOGS (Claude SWE-bench)")
    print("=" * 100)
    print("    Claude logs encode tool invocations as 'assistant' messages with tool_use blocks.")
    print("    Counting lines emitted by Write/Edit/MultiEdit/execute_code as a proxy for 'how much")
    print("    typing the model actually did to mutate files'.")

    edit_sizes = {}  # (arm, iid) -> total chars written
    with open(RAW, newline="") as f:
        for r in csv.DictReader(f):
            if r["agent"] != "claude" or r["benchmark"] != "swebench":
                continue
            if r["verdict"] == "env_fail":
                continue
            arm = r["arm"]; iid = r["instance_id"]
            log_path = REPO / r["result_path"]
            if not log_path.exists():
                continue
            chars = _count_edit_chars(log_path)
            edit_sizes[(arm, iid)] = chars

    if not edit_sizes:
        print("  No logs found.")
        return

    # Join with gold patch size + per-arm output tokens, compute correlations.
    print(f"\n  Parsed {len(edit_sizes)} log files.")
    arm_map = {"baseline": "baseline", "onlycode": "onlycode", "bash_only": "bash_only"}
    for arm in ("baseline", "onlycode", "bash_only"):
        xs, ys, gold = [], [], []
        for r in csub:
            iid = r["instance_id"]
            key = (arm, iid)
            if key in edit_sizes and r.get(f"{arm}_output_tokens") is not None:
                xs.append(edit_sizes[key])
                ys.append(r[f"{arm}_output_tokens"])
                gold.append(r["patch_lines_added"])
        if len(xs) < 5:
            continue
        rho_self, p_self = spearmanr(xs, ys)
        rho_gold, p_gold = spearmanr(xs, gold)
        print(f"  arm={arm:<10}  n={len(xs):3}  "
              f"corr(edit_chars, output_tokens) ρ={rho_self:+.3f} p={p_self:.3g}    "
              f"corr(edit_chars, gold_lines)    ρ={rho_gold:+.3f} p={p_gold:.3g}")

    # And the headline new test: does agent's *own* edit size correlate with
    # Δ_output_tokens (onlycode − baseline)?
    deltas = []
    for r in csub:
        iid = r["instance_id"]
        b = edit_sizes.get(("baseline", iid))
        o = edit_sizes.get(("onlycode", iid))
        d_tok = r.get("delta_output_tokens_onlycode_minus_baseline")
        if b is not None and o is not None and d_tok is not None:
            deltas.append((o - b, d_tok, r["patch_lines_added"]))
    if deltas:
        xs = [d[0] for d in deltas]
        ys = [d[1] for d in deltas]
        gxs = [d[2] for d in deltas]
        rho_d, p_d = spearmanr(xs, ys)
        rho_g, p_g = spearmanr(gxs, ys)
        print(f"\n  Δ_edit_chars (onlycode − baseline) vs Δ_output_tokens: ρ={rho_d:+.3f} p={p_d:.3g}  n={len(deltas)}")
        print(f"  gold patch_lines_added       vs Δ_output_tokens: ρ={rho_g:+.3f} p={p_g:.3g}  n={len(deltas)}")


def _count_edit_chars(log_path: Path) -> int:
    """Return total characters written via Write/Edit/MultiEdit tools or via
    execute_code Python content. Claude JSONL: each line is a JSON dict; we
    look for assistant turns containing tool_use blocks with text payloads."""
    total = 0
    try:
        with open(log_path) as f:
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
                    if not isinstance(blk, dict):
                        continue
                    if blk.get("type") != "tool_use":
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
    except Exception:
        return 0
    return total


if __name__ == "__main__":
    main()
