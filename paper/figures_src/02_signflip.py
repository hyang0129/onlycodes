"""Figure 2 — sign-flip headline (4-bar).

Single panel, 4 bars showing cost ratio ``code_only / cheapest-rival`` per
(benchmark, agent) cell. The 1.0 horizontal reference line is the visual
story; bars below = code-only cheaper, above = code-only more expensive.

Closest-rival contrast per cell (matches Table 1):

  * Artifact / Claude  → code_only / bash_only
  * Artifact / Codex   → code_only / bash_only
  * SWE-bench / Claude → onlycode  / baseline
  * SWE-bench / Codex  → onlycode  / baseline

Bar colour encodes significance × sign:
  * green-solid : ratio < 1.0 AND Wilcoxon p < 0.05 (code-only wins)
  * red-solid   : ratio > 1.0 AND Wilcoxon p < 0.05 (code-only loses)
  * grey-hatched: NS (p ≥ 0.05)

The numeric p-value is annotated above each bar (e.g., ``p<0.001``, ``p=0.12``).

Reads:  paper/data/paired_marginals.csv (per-arm marginal means)
        paper/data/paired_contrasts.csv (paired-Δ p-values)
Writes: paper/generated/figures/02_signflip.pdf
        paper/generated/figures/02_signflip.numbers.csv
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt

THIS_SCRIPT = "paper/figures_src/02_signflip.py"

# Per (benchmark, agent): (code-only arm, rival arm). Must match Table 1.
CONTRASTS = [
    ("artifact", "claude",  "code_only", "bash_only"),
    ("artifact", "codex",   "code_only", "bash_only"),
    ("swebench", "claude",  "onlycode",  "baseline"),
    ("swebench", "codex",   "onlycode",  "baseline"),
]

PANEL_LABELS = {
    ("artifact", "claude"): "Artifact\nClaude",
    ("artifact", "codex"):  "Artifact\nCodex",
    ("swebench", "claude"): "SWE-bench\nClaude",
    ("swebench", "codex"):  "SWE-bench\nCodex",
}


def _read_csv(path: Path) -> list[dict]:
    rows = []
    with path.open(newline="") as f:
        for line in f:
            if line.startswith("#"):
                continue
            f.seek(0)
            break
        # rewind and skip leading '#' lines via csv.DictReader
        with path.open(newline="") as f2:
            for line in f2:
                if not line.startswith("#"):
                    break
            # Reset and use DictReader with explicit comment-skipping.
        with path.open(newline="") as f3:
            lines = [ln for ln in f3 if not ln.startswith("#")]
        import io
        reader = csv.DictReader(io.StringIO("".join(lines)))
        for r in reader:
            rows.append(r)
    return rows


def lookup_means(marginals: list[dict]) -> dict[tuple, float]:
    """{(bench, agent, arm): mean cost_adj}"""
    out = {}
    for r in marginals:
        if r["metric"] != "cost_adj":
            continue
        out[(r["benchmark"], r["agent"], r["arm"])] = float(r["mean"])
    return out


def lookup_pvals(contrasts: list[dict]) -> dict[tuple, float]:
    """{(bench, agent, contrast_string): wilcoxon_p}"""
    out = {}
    for r in contrasts:
        if r["metric"] != "cost_adj":
            continue
        if not r["wilcoxon_p"]:
            continue
        out[(r["benchmark"], r["agent"], r["contrast"])] = float(r["wilcoxon_p"])
    return out


def p_label(p: float) -> str:
    if p < 0.001:
        return "p<0.001"
    return f"p={p:.2f}"


def render_figure(marginals, contrasts, out_path: Path):
    plt.rcParams.update({
        "font.family": "serif",
        "font.size": 9,
        "axes.labelsize": 9,
        "axes.titlesize": 10,
        "xtick.labelsize": 9,
        "ytick.labelsize": 8,
        "pdf.fonttype": 42,
    })

    means = lookup_means(marginals)
    pvals = lookup_pvals(contrasts)

    fig, ax = plt.subplots(figsize=(4.4, 3.0))

    rows = []
    xs = list(range(len(CONTRASTS)))
    ratios, colors, hatches, p_strs, p_vals = [], [], [], [], []

    for bench, agent, code_arm, rival_arm in CONTRASTS:
        m_code = means[(bench, agent, code_arm)]
        m_rival = means[(bench, agent, rival_arm)]
        ratio = m_code / m_rival
        contrast_id = f"{code_arm}-vs-{rival_arm}"
        p = pvals[(bench, agent, contrast_id)]
        ratios.append(ratio)
        p_vals.append(p)
        p_strs.append(p_label(p))

        sig = p < 0.05
        if not sig:
            colors.append("#bbbbbb")
            hatches.append("///")
        elif ratio < 1.0:
            colors.append("#2a7a3a")     # green: code-only wins
            hatches.append("")
        else:
            colors.append("#a13030")     # red: code-only loses
            hatches.append("")

        rows.append({
            "bench": bench, "agent": agent,
            "code_arm": code_arm, "rival_arm": rival_arm,
            "code_mean": m_code, "rival_mean": m_rival,
            "ratio": ratio, "p": p,
        })

    bars = ax.bar(xs, ratios, width=0.7, color=colors, edgecolor="black", linewidth=0.6)
    for bar, hatch in zip(bars, hatches):
        if hatch:
            bar.set_hatch(hatch)

    ax.axhline(1.0, color="black", linewidth=0.9, linestyle="-")

    # Significance/value annotations above each bar.
    for i, (ratio, p_str, p) in enumerate(zip(ratios, p_strs, p_vals)):
        label_top = max(ratio, 1.0) + 0.04
        ax.text(i, label_top, p_str, ha="center", va="bottom", fontsize=9)
        # Ratio value inside the bar (or above, if bar < 1). White text on
        # solid-coloured bars (significant green/red); black text on hatched
        # NS bars so the digit reads against the lighter pattern.
        sig = p < 0.05
        y_inside = min(ratio - 0.04, 0.96) if ratio < 1.0 else ratio + 0.10
        va = "top" if ratio < 1.0 else "bottom"
        text_color = "white" if (ratio < 1.0 and sig) else "black"
        ax.text(i, y_inside, f"{ratio:.2f}", ha="center", va=va, fontsize=8, color=text_color)

    ax.set_xticks(xs)
    ax.set_xticklabels([PANEL_LABELS[(b, a)] for b, a, _, _ in CONTRASTS])
    ax.set_ylabel("Cost ratio  (code-only / cheapest rival)")

    # Y-axis: tight around 1.0 with enough headroom for sig stars.
    y_max = max(max(ratios), 1.0) + 0.18
    y_min = min(min(ratios), 1.0) - 0.10
    ax.set_ylim(y_min, y_max)

    # Visual separator between Artifact and SWE-bench pair groups.
    ax.axvline(1.5, color="0.7", linewidth=0.5, linestyle="--")

    fig.tight_layout(pad=0.4)
    fig.savefig(out_path, format="pdf", bbox_inches="tight")
    plt.close(fig)
    return rows


def write_sidecar(rows: list[dict], out_path: Path, source_data: str):
    out_rows = []
    for r in rows:
        cell = f"{r['bench']}-{r['agent']}"
        out_rows.append({"label": f"{cell}:ratio",       "value": f"{r['ratio']:.6f}",       "role": "ratio"})
        out_rows.append({"label": f"{cell}:p",           "value": f"{r['p']:.6e}",            "role": "p_value"})
        out_rows.append({"label": f"{cell}:code_mean",   "value": f"{r['code_mean']:.6f}",    "role": "cost_usd"})
        out_rows.append({"label": f"{cell}:rival_mean",  "value": f"{r['rival_mean']:.6f}",   "role": "cost_usd"})

    with out_path.open("w", newline="") as f:
        f.write(f"# generator: {THIS_SCRIPT}\n")
        f.write(f"# source_data: {source_data}\n")
        w = csv.DictWriter(f, fieldnames=["label", "value", "role"])
        w.writeheader()
        for r in out_rows:
            w.writerow(r)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--paper-dir", type=Path, default=Path(__file__).resolve().parents[1])
    args = ap.parse_args()
    paper_dir: Path = args.paper_dir

    marg_path = paper_dir / "data" / "paired_marginals.csv"
    cont_path = paper_dir / "data" / "paired_contrasts.csv"
    out_dir = paper_dir / "generated" / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / "02_signflip.pdf"
    sidecar_path = out_dir / "02_signflip.numbers.csv"

    marginals = _read_csv(marg_path)
    contrasts = _read_csv(cont_path)
    rows = render_figure(marginals, contrasts, pdf_path)
    src = f"{marg_path.relative_to(paper_dir.parent)} + {cont_path.relative_to(paper_dir.parent)}"
    write_sidecar(rows, sidecar_path, source_data=src)
    print(f"  wrote {pdf_path}")
    print(f"  wrote {sidecar_path}")


if __name__ == "__main__":
    main()
