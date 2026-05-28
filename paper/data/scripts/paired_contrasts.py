"""Paired-contrast stats over paper/data/all_results.csv.

Per (benchmark, agent):
  1. For each (instance_id, arm), mean the available metrics across seeds.
     This collapses seed-level noise to one number per (instance, arm).
  2. Per-arm marginal: mean of per-instance means; SE = SD_instance / sqrt(n).
     Instances are the independent unit; seeds within an instance are not.
  3. For each ordered arm pair (A, B), per-instance Δ = mean_A - mean_B. Report
     n, mean Δ, SE_Δ, 95% CI, Wilcoxon signed-rank p (paired, robust to heavy
     tails). Pass rate uses the same per-instance pass-rate (in {0, 1/3, 2/3, 1})
     and Wilcoxon — a within-instance analogue of McNemar.

Reads paper/data/all_results.csv. Default mode prints a human-readable report
to stdout. With ``--csv`` emits two sidecar CSVs the paper build pipeline picks
up automatically:

  * ``paper/data/paired_contrasts.csv`` — one row per
    ``(benchmark, agent, contrast, metric)`` with Δ, SE, 95% CI, Wilcoxon p, n.
  * ``paper/data/paired_marginals.csv`` — one row per
    ``(benchmark, agent, arm, metric)`` with mean, SE, n.

Both files carry the provenance header ``build_numbers.py`` expects.

Run from repo root:
    python paper/data/scripts/paired_contrasts.py            # report only
    python paper/data/scripts/paired_contrasts.py --csv      # report + CSVs
"""
from __future__ import annotations
import argparse, csv, datetime, math, statistics, subprocess
from collections import defaultdict
from pathlib import Path
from scipy.stats import wilcoxon

REPO_ROOT = Path(__file__).resolve().parents[3]
# all_results.csv lives under data/raw/ to keep it out of build_numbers.py's
# top-level paper/data/*.csv glob — only the paper-citation CSVs (this script's
# outputs, headline.csv, etc.) live directly under paper/data/.
CSV_PATH = Path(__file__).resolve().parents[1] / "raw" / "all_results.csv"
DATA_DIR = Path(__file__).resolve().parents[1]
THIS_SCRIPT = Path(__file__).relative_to(REPO_ROOT)

METRIC_LABELS = [
    ("pass", "pass rate", "rate"),
    ("cost", "cost (USD)", "cost"),
    ("cost_adj", "cost adj (USD)", "cost"),
    ("turns", "turns", "turns"),
    ("tool_calls", "tool calls", "turns"),
    ("llm_calls", "LLM calls", "turns"),
    ("wall", "wall (s)", "wall"),
    ("input_tokens", "input tok", "tok"),
    ("cached_input_tokens", "cached in tok", "tok"),
    ("output_tokens", "output tok", "tok"),
]


def load_rows(path: Path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def to_float(s):
    if s in (None, "", "NA"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def per_instance_means(rows, benchmark: str, agent: str):
    """Return {arm: {instance_id: {metric: mean_across_seeds}}} for one (benchmark, agent)."""
    # Group raw values per (arm, instance, metric).
    bucket: dict[str, dict[str, dict[str, list[float]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for r in rows:
        if r["benchmark"] != benchmark or r["agent"] != agent:
            continue
        if r["verdict"] == "env_fail":
            # env_fail is a harness failure, not a model attempt — exclude from all metrics.
            continue
        arm = r["arm"]
        inst = r["instance_id"]
        is_pass = 1.0 if r["verdict"] == "PASS" else 0.0
        bucket[arm][inst]["pass"].append(is_pass)
        for src, dst in (
            ("cost_usd", "cost"),
            ("cost_usd_adjusted", "cost_adj"),
            ("num_turns", "turns"),
            ("tool_calls", "tool_calls"),
            ("llm_calls", "llm_calls"),
            ("wall_secs", "wall"),
            ("input_tokens", "input_tokens"),
            ("cached_input_tokens", "cached_input_tokens"),
            ("output_tokens", "output_tokens"),
        ):
            v = to_float(r[src])
            if v is not None:
                bucket[arm][inst][dst].append(v)
    out: dict[str, dict[str, dict[str, float]]] = {}
    for arm, by_inst in bucket.items():
        out[arm] = {}
        for inst, by_metric in by_inst.items():
            out[arm][inst] = {m: statistics.fmean(vs) for m, vs in by_metric.items() if vs}
    return out


def marginal(per_inst):
    out = {}
    metrics = set().union(*[set(v.keys()) for v in per_inst.values()]) if per_inst else set()
    for m in metrics:
        vals = [v[m] for v in per_inst.values() if m in v]
        n = len(vals)
        if n == 0:
            out[m] = (float("nan"), float("nan"), 0); continue
        mean = statistics.fmean(vals)
        sd = statistics.stdev(vals) if n > 1 else 0.0
        out[m] = (mean, sd / math.sqrt(n), n)
    return out


def paired_diff(per_arm, a, b, metric):
    A, B = per_arm.get(a, {}), per_arm.get(b, {})
    common = sorted(set(A) & set(B))
    return [A[t][metric] - B[t][metric] for t in common if metric in A[t] and metric in B[t]]


def contrast_stats(per_arm, a, b, metric):
    """Return dict of (mean_delta, se, ci_lo, ci_hi, wilcoxon_p, n_pairs) or None."""
    d = paired_diff(per_arm, a, b, metric)
    n = len(d)
    if n == 0:
        return None
    mean = statistics.fmean(d)
    sd = statistics.stdev(d) if n > 1 else 0.0
    se = sd / math.sqrt(n) if n > 0 else float("nan")
    ci_lo = mean - 1.96 * se
    ci_hi = mean + 1.96 * se
    try:
        if all(abs(x) < 1e-12 for x in d):
            pval = float("nan")
        else:
            pval = float(wilcoxon(d, zero_method="wilcox", alternative="two-sided", method="auto").pvalue)
    except Exception:
        pval = float("nan")
    return {
        "mean_delta": mean,
        "se": se,
        "ci_lo": ci_lo,
        "ci_hi": ci_hi,
        "wilcoxon_p": pval,
        "n_pairs": n,
        "mean_a": statistics.fmean([per_arm[a][t][metric] for t in per_arm[a] if metric in per_arm[a][t]]) if per_arm.get(a) else float("nan"),
        "mean_b": statistics.fmean([per_arm[b][t][metric] for t in per_arm[b] if metric in per_arm[b][t]]) if per_arm.get(b) else float("nan"),
    }


def report(label, arms, rows, benchmark, agent):
    per_arm = per_instance_means(rows, benchmark, agent)
    # Filter to arms actually present.
    arms = [a for a in arms if a in per_arm]
    if len(arms) < 2:
        print(f"\n{'='*100}\n{label}\n{'='*100}\n  (insufficient arms present: {list(per_arm.keys())})")
        return

    print(f"\n{'='*100}\n{label}\n{'='*100}")

    print("\n-- Marginal means (per-instance mean across seeds, then average over instances) --")
    hdr = f"{'arm':<11}" + "".join(f"{lbl:>26}" for _, lbl, _ in METRIC_LABELS)
    print(hdr); print("-" * len(hdr))
    for arm in arms:
        marg = marginal(per_arm[arm])
        row = f"{arm:<11}"
        for key, _, kind in METRIC_LABELS:
            m, se, n = marg.get(key, (float("nan"), float("nan"), 0))
            if kind == "rate":
                row += f"  {m*100:>6.2f}% ± {se*100:>5.2f}% [{n:>3}]  "
            elif kind == "cost":
                row += f"  {m:>7.4f} ± {se:>6.4f} [{n:>3}]  "
            elif kind == "turns":
                row += f"  {m:>6.2f} ± {se:>5.2f} [{n:>3}]    "
            elif kind == "tok":
                row += f"  {m:>9,.0f} ± {se:>7,.0f} [{n:>3}]"
            else:  # wall
                row += f"  {m:>7.1f} ± {se:>6.1f} [{n:>3}]    "
        print(row)

    pairs = []
    for i in range(len(arms)):
        for j in range(i + 1, len(arms)):
            pairs.append((arms[i], arms[j]))
    print("\n-- Paired per-instance contrasts (Δ = A − B): mean Δ ± SE, 95% CI, Wilcoxon p --")
    for a, b in pairs:
        print(f"\n  {a} − {b}:")
        for key, lbl, kind in METRIC_LABELS:
            d = paired_diff(per_arm, a, b, key)
            n = len(d)
            if n == 0:
                print(f"    {lbl:<18}  (no data)"); continue
            mean = statistics.fmean(d)
            sd = statistics.stdev(d) if n > 1 else 0.0
            se = sd / math.sqrt(n)
            ci_lo = mean - 1.96 * se; ci_hi = mean + 1.96 * se
            try:
                if all(abs(x) < 1e-12 for x in d):
                    pval = float("nan")
                else:
                    pval = float(wilcoxon(d, zero_method="wilcox", alternative="two-sided", method="auto").pvalue)
            except Exception:
                pval = float("nan")
            if kind == "rate":
                ms, ses = f"{mean*100:+7.3f}pp", f"{se*100:6.3f}pp"
                cis = f"[{ci_lo*100:+7.3f}, {ci_hi*100:+7.3f}]pp"
            elif kind == "cost":
                ms, ses = f"{mean:+8.4f}", f"{se:8.4f}"
                cis = f"[{ci_lo:+7.4f}, {ci_hi:+7.4f}]"
            elif kind == "turns":
                ms, ses = f"{mean:+7.3f}", f"{se:6.3f}"
                cis = f"[{ci_lo:+6.2f}, {ci_hi:+6.2f}]"
            elif kind == "tok":
                ms, ses = f"{mean:+11,.0f}", f"{se:9,.0f}"
                cis = f"[{ci_lo:+11,.0f}, {ci_hi:+11,.0f}]"
            else:  # wall
                ms, ses = f"{mean:+8.2f}", f"{se:7.2f}"
                cis = f"[{ci_lo:+7.1f}, {ci_hi:+7.1f}]"
            sig = "***" if pval < 0.001 else "**" if pval < 0.01 else "*" if pval < 0.05 else ""
            print(f"    {lbl:<18}  Δ={ms} ± {ses}  CI95={cis}  p={pval:.3g} {sig}  [n={n}]")


def _git_head_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def _provenance_header(key_schema: str, default_precision: int, description: str) -> list[str]:
    return [
        f"# source_commit: {_git_head_sha()}",
        f"# generated: {datetime.datetime.utcnow().replace(microsecond=0).isoformat()}Z",
        f"# generator: {THIS_SCRIPT}",
        f"# key_schema: {key_schema}",
        f"# default_precision: {default_precision}",
        f"# {description}",
    ]


def _write_csv_with_header(path: Path, header_lines: list[str], fieldnames: list[str], rows: list[dict]):
    with path.open("w", newline="") as f:
        for line in header_lines:
            f.write(line + "\n")
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _fmt(v) -> str:
    """Numeric → string with full precision; NaN → empty string."""
    if v is None:
        return ""
    if isinstance(v, float):
        if math.isnan(v):
            return ""
        return repr(v)
    return str(v)


def emit_csvs(rows, arms_for: dict[str, list[str]], out_dir: Path):
    """Write paired_contrasts.csv (deltas) and paired_marginals.csv (arm means)."""
    cells = sorted({(r["benchmark"], r["agent"]) for r in rows})

    contrast_rows: list[dict] = []
    marginal_rows: list[dict] = []

    for benchmark, agent in cells:
        arms_canon = arms_for.get(benchmark, [])
        per_arm = per_instance_means(rows, benchmark, agent)
        arms = [a for a in arms_canon if a in per_arm]
        if not arms:
            continue

        # Per-arm marginals.
        for arm in arms:
            marg = marginal(per_arm[arm])
            for metric_key, _label, _kind in METRIC_LABELS:
                m, se, n = marg.get(metric_key, (float("nan"), float("nan"), 0))
                marginal_rows.append({
                    "benchmark": benchmark,
                    "agent": agent,
                    "arm": arm,
                    "metric": metric_key,
                    "mean": _fmt(m),
                    "se": _fmt(se),
                    "n": n,
                })

        # Emit contrasts in BOTH orientations (A-vs-B and B-vs-A) so callers
        # can pick whichever subtraction direction reads cleanly in prose
        # without having to negate at the LaTeX layer. Wilcoxon p is symmetric;
        # mean_delta and CI bounds flip sign; mean_a/mean_b swap.
        for i in range(len(arms)):
            for j in range(len(arms)):
                if i == j:
                    continue
                a, b = arms[i], arms[j]
                contrast_id = f"{a}-vs-{b}"
                for metric_key, _label, _kind in METRIC_LABELS:
                    cs = contrast_stats(per_arm, a, b, metric_key)
                    if cs is None:
                        continue
                    contrast_rows.append({
                        "benchmark": benchmark,
                        "agent": agent,
                        "contrast": contrast_id,
                        "metric": metric_key,
                        "mean_delta": _fmt(cs["mean_delta"]),
                        "se": _fmt(cs["se"]),
                        "ci_lo": _fmt(cs["ci_lo"]),
                        "ci_hi": _fmt(cs["ci_hi"]),
                        "wilcoxon_p": _fmt(cs["wilcoxon_p"]),
                        "n_pairs": cs["n_pairs"],
                        "mean_a": _fmt(cs["mean_a"]),
                        "mean_b": _fmt(cs["mean_b"]),
                    })

    _write_csv_with_header(
        out_dir / "paired_contrasts.csv",
        _provenance_header(
            key_schema="benchmark:agent:contrast:metric",
            default_precision=4,
            description=(
                "Paired per-instance contrasts. contrast='A-vs-B' means metric_A - metric_B "
                "computed within each instance, averaged across instances. wilcoxon_p is the "
                "paired Wilcoxon signed-rank two-sided p-value."
            ),
        ),
        fieldnames=["benchmark", "agent", "contrast", "metric",
                    "mean_delta", "se", "ci_lo", "ci_hi",
                    "wilcoxon_p", "n_pairs", "mean_a", "mean_b"],
        rows=contrast_rows,
    )
    _write_csv_with_header(
        out_dir / "paired_marginals.csv",
        _provenance_header(
            key_schema="benchmark:agent:arm:metric",
            default_precision=4,
            description=(
                "Per-arm marginal means. mean = average over per-instance means "
                "(themselves the mean across seeds); SE = SD_instance / sqrt(n_instances)."
            ),
        ),
        fieldnames=["benchmark", "agent", "arm", "metric", "mean", "se", "n"],
        rows=marginal_rows,
    )
    print(f"\nWrote {len(contrast_rows)} contrast rows to {out_dir / 'paired_contrasts.csv'}")
    print(f"Wrote {len(marginal_rows)} marginal rows to {out_dir / 'paired_marginals.csv'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", action="store_true",
                    help="Also write paper/data/paired_contrasts.csv and paired_marginals.csv.")
    ap.add_argument("--out-dir", type=Path, default=DATA_DIR,
                    help="Directory to write CSVs into (default: paper/data/).")
    args = ap.parse_args()

    rows = load_rows(CSV_PATH)
    cells = sorted({(r["benchmark"], r["agent"]) for r in rows})
    arms_for = {
        "artifact": ["code_only", "tool_rich", "bash_only"],
        "swebench": ["baseline", "onlycode", "bash_only"],
    }
    for benchmark, agent in cells:
        arms = arms_for.get(benchmark, [])
        label = f"{benchmark.upper()} · agent={agent} (per-instance means across seeds, paired across arms)"
        report(label, arms, rows, benchmark, agent)

    if args.csv:
        emit_csvs(rows, arms_for, args.out_dir)


if __name__ == "__main__":
    main()
