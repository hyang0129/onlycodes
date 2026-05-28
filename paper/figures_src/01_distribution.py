"""Figure 1 — per-cell per-instance Δ cost-adjusted distribution.

A 2×2 small-multiples panel showing, for each (benchmark, agent) cell, the
sorted per-instance Δ cost_usd_adjusted (code-only − cheapest rival, computed
as the mean across 3 seeds for each instance). Anchors §5.2 in the paper.

Closest-rival contrast per cell (matches Table 1):

  * Artifact / Claude  → code_only − bash_only
  * Artifact / Codex   → code_only − bash_only
  * SWE-bench / Claude → onlycode  − baseline
  * SWE-bench / Codex  → onlycode  − baseline

Reads:  paper/data/raw/all_results.csv (per-row, all seeds × arms × instances)
Writes: paper/generated/figures/01_distribution.pdf
        paper/generated/figures/01_distribution.numbers.csv

Sidecar exposes per-cell summary stats (median Δ, n_wins, n_total, p25/p75)
for citation in §5 prose via \\result{fig.01_distribution}{...}.
"""
from __future__ import annotations

import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt

THIS_SCRIPT = "paper/figures_src/01_distribution.py"

# Per (benchmark, agent): the (code-only arm, cheapest-rival arm) pair. Must
# match the Table 1 closest-cost rival choice in paper/data/scripts/paired_contrasts.py
# and sections/05_results.tex.
CONTRASTS = {
    ("artifact", "claude"):  ("code_only", "bash_only"),
    ("artifact", "codex"):   ("code_only", "bash_only"),
    ("swebench", "claude"):  ("onlycode", "baseline"),
    ("swebench", "codex"):   ("onlycode", "baseline"),
}

# Display order (row-major): rows = benchmark, cols = agent.
PANELS = [
    ("artifact",  "claude"), ("artifact",  "codex"),
    ("swebench",  "claude"), ("swebench",  "codex"),
]

PANEL_TITLES = {
    ("artifact",  "claude"): "Artifact · Claude",
    ("artifact",  "codex"):  "Artifact · Codex",
    ("swebench",  "claude"): "SWE-bench · Claude",
    ("swebench",  "codex"):  "SWE-bench · Codex",
}


def load_per_instance_means(csv_path: Path):
    """Return {(bench, agent, arm): {instance_id: mean_cost_adj_across_seeds}}."""
    buckets: dict[tuple, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    with csv_path.open(newline="") as f:
        for row in csv.DictReader(f):
            if row.get("verdict") == "env_fail":
                continue
            v = row.get("cost_usd_adjusted")
            if v in (None, "", "None"):
                continue
            try:
                v = float(v)
            except ValueError:
                continue
            buckets[(row["benchmark"], row["agent"], row["arm"])][row["instance_id"]].append(v)
    out: dict[tuple, dict[str, float]] = {}
    for key, inst_map in buckets.items():
        out[key] = {inst: statistics.fmean(vs) for inst, vs in inst_map.items() if vs}
    return out


def per_instance_deltas(per_arm: dict, bench: str, agent: str) -> list[tuple[str, float, float, float]]:
    """Return [(instance_id, code_only_cost, rival_cost, delta)] sorted by delta."""
    code_arm, rival_arm = CONTRASTS[(bench, agent)]
    code_map = per_arm.get((bench, agent, code_arm), {})
    rival_map = per_arm.get((bench, agent, rival_arm), {})
    common = sorted(set(code_map) & set(rival_map))
    rows = [
        (inst, code_map[inst], rival_map[inst], code_map[inst] - rival_map[inst])
        for inst in common
    ]
    rows.sort(key=lambda r: r[3])
    return rows


def render_figure(per_arm, out_path: Path):
    plt.rcParams.update({
        "font.family": "serif",
        "font.size": 9,
        "axes.labelsize": 9,
        "axes.titlesize": 10,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "pdf.fonttype": 42,  # TrueType, for editable PDF
    })

    fig, axes = plt.subplots(2, 2, figsize=(6.4, 4.4), sharex=False, sharey=False)
    axes_flat = axes.flat

    panel_stats: list[dict] = []
    for ax, (bench, agent) in zip(axes_flat, PANELS):
        rows = per_instance_deltas(per_arm, bench, agent)
        deltas = [r[3] for r in rows]
        n = len(deltas)
        n_win = sum(1 for d in deltas if d < 0)
        median = statistics.median(deltas) if deltas else 0.0
        p25 = deltas[n // 4] if n >= 4 else float("nan")
        p75 = deltas[3 * n // 4] if n >= 4 else float("nan")

        x = list(range(1, n + 1))
        # Color by sign: green for code-only-wins (<0), red for code-only-loses (>0).
        # Use solid bars; the asymmetry is what we want to expose visually.
        bar_colors = ["#2a7a3a" if d < 0 else "#a13030" for d in deltas]
        ax.bar(x, deltas, color=bar_colors, width=1.0, edgecolor="none")

        ax.axhline(0.0, color="black", linewidth=0.8)
        ax.axhline(median, color="black", linewidth=0.8, linestyle="--", alpha=0.5)

        ax.set_title(PANEL_TITLES[(bench, agent)])
        ax.set_xlabel("instance (sorted)")
        ax.set_ylabel("Δ cost adj. (USD)" if agent == "claude" else "")
        ax.set_xlim(0.5, n + 0.5)

        # Annotation: median + win fraction in a low-key corner box.
        annot = f"median Δ = ${median:+.4f}\nn_win / n = {n_win}/{n}"
        ax.text(
            0.04, 0.04, annot, transform=ax.transAxes,
            fontsize=7, va="bottom", ha="left",
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="0.7", lw=0.5, alpha=0.9),
        )

        panel_stats.append({
            "bench": bench, "agent": agent, "n": n, "n_win": n_win,
            "median_delta": median, "p25_delta": p25, "p75_delta": p75,
            "min_delta": deltas[0] if deltas else float("nan"),
            "max_delta": deltas[-1] if deltas else float("nan"),
        })

    fig.tight_layout(pad=0.6, w_pad=1.0, h_pad=1.0)
    fig.savefig(out_path, format="pdf", bbox_inches="tight")
    plt.close(fig)
    return panel_stats


def write_sidecar(panel_stats: list[dict], out_path: Path, source_data: str):
    rows = []
    for st in panel_stats:
        cell = f"{st['bench']}-{st['agent']}"
        rows.append({"label": f"{cell}:n", "value": st["n"], "role": "count"})
        rows.append({"label": f"{cell}:n_win", "value": st["n_win"], "role": "count"})
        rows.append({"label": f"{cell}:median_delta", "value": f"{st['median_delta']:.6f}", "role": "delta_usd"})
        rows.append({"label": f"{cell}:p25_delta", "value": f"{st['p25_delta']:.6f}", "role": "delta_usd"})
        rows.append({"label": f"{cell}:p75_delta", "value": f"{st['p75_delta']:.6f}", "role": "delta_usd"})
        rows.append({"label": f"{cell}:min_delta", "value": f"{st['min_delta']:.6f}", "role": "delta_usd"})
        rows.append({"label": f"{cell}:max_delta", "value": f"{st['max_delta']:.6f}", "role": "delta_usd"})

    with out_path.open("w", newline="") as f:
        f.write(f"# generator: {THIS_SCRIPT}\n")
        f.write(f"# source_data: {source_data}\n")
        w = csv.DictWriter(f, fieldnames=["label", "value", "role"])
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--paper-dir", type=Path, default=Path(__file__).resolve().parents[1])
    args = ap.parse_args()
    paper_dir: Path = args.paper_dir

    src = paper_dir / "data" / "raw" / "all_results.csv"
    out_dir = paper_dir / "generated" / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / "01_distribution.pdf"
    sidecar_path = out_dir / "01_distribution.numbers.csv"

    per_arm = load_per_instance_means(src)
    stats = render_figure(per_arm, pdf_path)
    write_sidecar(stats, sidecar_path, source_data=str(src.relative_to(paper_dir.parent)))
    print(f"  wrote {pdf_path}")
    print(f"  wrote {sidecar_path}")


if __name__ == "__main__":
    main()
