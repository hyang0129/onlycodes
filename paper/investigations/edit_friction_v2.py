"""Edit-friction hypothesis: deeper tests beyond the primary Spearman correlation.

Adds three views the primary script doesn't have:

  (A) Within-arm slope test. For each (agent, arm), fit
      output_tokens ~ patch_lines_added (OLS) and compare slopes across arms.
      Hypothesis: Claude onlycode's slope > Claude baseline's slope.

  (B) Median-split contrast. Split instances by patch_lines_added into low/high
      halves; report Claude onlycode-vs-baseline Δ_output_tokens in each half
      (mean, Wilcoxon p). Hypothesis: |Δ| is larger in the high-patch half.

  (C) Robustness: rank-based partial correlation that conditions on baseline
      output_tokens (a proxy for raw task difficulty). If the patch-size
      signal disappears after conditioning on baseline tokens, the apparent
      correlation may be difficulty-confounding rather than edit-friction.

Reads paper/investigations/edit_friction_data.csv (produced by
edit_friction_analysis.py).
"""
from __future__ import annotations
import csv
import statistics
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr, wilcoxon

DATA = Path(__file__).parent / "edit_friction_data.csv"


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
                    try:
                        r[k] = float(v)
                    except ValueError:
                        r[k] = None
            rows.append(r)
    return rows


def ols_slope(x, y):
    """Return (slope, intercept, r2) for y = a*x + b."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)
    if n < 3 or x.std() == 0:
        return float("nan"), float("nan"), float("nan")
    slope, intercept = np.polyfit(x, y, 1)
    yhat = slope * x + intercept
    ss_res = np.sum((y - yhat) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return float(slope), float(intercept), float(r2)


def bootstrap_slope_diff(x, y_a, y_b, n_boot=5000, seed=0):
    """Bootstrap 95% CI for (slope_a − slope_b)."""
    rng = np.random.default_rng(seed)
    x = np.asarray(x, float); y_a = np.asarray(y_a, float); y_b = np.asarray(y_b, float)
    n = len(x)
    diffs = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        bx = x[idx]
        if bx.std() == 0:
            continue
        s_a, _ = np.polyfit(bx, y_a[idx], 1)
        s_b, _ = np.polyfit(bx, y_b[idx], 1)
        diffs.append(s_a - s_b)
    diffs = np.array(diffs)
    if not len(diffs):
        return float("nan"), float("nan"), float("nan")
    return float(np.mean(diffs)), float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def per_agent(rows, agent):
    return [r for r in rows if r["agent"] == agent and r["benchmark"] == "swebench"]


def main():
    rows = load_rows()
    print(f"Loaded {len(rows)} rows (one per benchmark x agent x instance) from {DATA.name}")

    # ----- (A) Within-arm slope test -----
    print("\n" + "=" * 100)
    print("(A) WITHIN-ARM SLOPE: output_tokens = a * patch_lines_added + b")
    print("=" * 100)

    for agent in ("claude", "codex"):
        sub = per_agent(rows, agent)
        x = [r["patch_lines_added"] for r in sub]
        print(f"\n  Agent={agent}  n={len(sub)}  patch_lines_added (min,med,max)="
              f"({min(x):.0f}, {statistics.median(x):.0f}, {max(x):.0f})")
        slopes = {}
        arm_cols = {"baseline": "baseline_output_tokens",
                    "onlycode": "onlycode_output_tokens",
                    "bash_only": "bash_only_output_tokens"}
        for arm, col in arm_cols.items():
            xs, ys = [], []
            for r in sub:
                if r.get(col) is not None:
                    xs.append(r["patch_lines_added"])
                    ys.append(r[col])
            slope, intercept, r2 = ols_slope(xs, ys)
            slopes[arm] = (slope, intercept, r2, len(xs))
            print(f"    {arm:<10} slope={slope:+.3f} tok/line  intercept={intercept:+8.1f}  R²={r2:.3f}  n={len(xs)}")
        # Compare slopes (paired across instances) for onlycode vs baseline.
        if all(arm in slopes for arm in ("onlycode", "baseline")):
            xs, ya, yb = [], [], []
            for r in sub:
                if r.get("onlycode_output_tokens") is not None and r.get("baseline_output_tokens") is not None:
                    xs.append(r["patch_lines_added"])
                    ya.append(r["onlycode_output_tokens"])
                    yb.append(r["baseline_output_tokens"])
            mean_d, lo, hi = bootstrap_slope_diff(xs, ya, yb)
            print(f"    slope(onlycode) − slope(baseline) = {mean_d:+.3f}  95% CI [{lo:+.3f}, {hi:+.3f}]  n={len(xs)}")

    # ----- (B) Median-split contrast -----
    print("\n" + "=" * 100)
    print("(B) MEDIAN-SPLIT: Δ_output_tokens (onlycode − baseline) in low- vs high-patch halves")
    print("=" * 100)

    for agent in ("claude", "codex"):
        sub = per_agent(rows, agent)
        pairs = [(r["patch_lines_added"],
                  r.get("delta_output_tokens_onlycode_minus_baseline"))
                 for r in sub if r.get("delta_output_tokens_onlycode_minus_baseline") is not None]
        if not pairs:
            print(f"\n  Agent={agent}: no data")
            continue
        xs = sorted(p[0] for p in pairs)
        median_x = statistics.median(xs)
        low = [d for x, d in pairs if x <= median_x]
        high = [d for x, d in pairs if x > median_x]
        print(f"\n  Agent={agent}  n={len(pairs)}  median patch_lines_added={median_x:.0f}")
        for label, vals in (("low", low), ("high", high)):
            if not vals:
                continue
            m = statistics.fmean(vals)
            sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
            se = sd / (len(vals) ** 0.5)
            try:
                w = float(wilcoxon(vals, alternative="two-sided").pvalue)
            except Exception:
                w = float("nan")
            print(f"    {label:<5} n={len(vals):<3} mean Δ output_tokens = {m:+8.1f} ± {se:7.1f}  wilcoxon p = {w:.3g}")
        # Test whether high-patch half has larger |Δ| than low-patch half.
        if low and high:
            # Mann-Whitney on signed Δ (one-sided high > low).
            from scipy.stats import mannwhitneyu
            mw = mannwhitneyu(high, low, alternative="greater").pvalue
            print(f"    one-sided MW p(high > low) = {mw:.3g}")

    # ----- (C) Partial correlation conditioning on baseline output_tokens -----
    print("\n" + "=" * 100)
    print("(C) PARTIAL: rank-corr(patch_lines_added, Δ_output_tokens | baseline_output_tokens)")
    print("=" * 100)
    print("    Method: rank each variable, then OLS Δ = a + b*ranked_baseline; correlate residuals with ranked patch_lines_added.")

    for agent in ("claude", "codex"):
        sub = per_agent(rows, agent)
        triples = [(r["patch_lines_added"], r.get("baseline_output_tokens"),
                    r.get("delta_output_tokens_onlycode_minus_baseline"))
                   for r in sub
                   if r.get("baseline_output_tokens") is not None
                   and r.get("delta_output_tokens_onlycode_minus_baseline") is not None]
        if not triples:
            continue
        from scipy.stats import rankdata
        px = np.asarray([t[0] for t in triples], float)
        bo = np.asarray([t[1] for t in triples], float)
        do = np.asarray([t[2] for t in triples], float)
        # Raw Spearman.
        rho_raw = spearmanr(px, do).statistic
        # Partial.
        rpx = rankdata(px); rbo = rankdata(bo); rdo = rankdata(do)
        b1, _ = np.polyfit(rbo, rpx, 1); res_x = rpx - b1 * rbo
        b2, _ = np.polyfit(rbo, rdo, 1); res_y = rdo - b2 * rbo
        rho_partial = spearmanr(res_x, res_y).statistic
        print(f"  agent={agent}  n={len(triples)}  ρ_raw={rho_raw:+.3f}  ρ_partial(|baseline_tok)={rho_partial:+.3f}")


if __name__ == "__main__":
    main()
