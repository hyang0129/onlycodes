"""Figure 4 — H2 per-call truncation case study.

Horizontal bar chart showing the per-call output character count for one
LLM step from django__django-11848 (Codex, seed 1, both arms PASS):

  * baseline arm: 40,165 chars — pinned the exec_command cap (40,154);
    inline annotation marks the truncated tail (3,918 tokens elided).
  * onlycode  arm: 1,514 chars — well under the cap.

Intent-only labels: bars carry "broad keyword sweep" and "single-pattern
grep" (per Design decision §6 of figures_outline.md), NOT the literal
regex or codebox.grep arguments. Visual punchline is the cap line + red
truncation tail vs. the small onlycode bar; the intent labels carry why.

Reads:  paper/data/h2_truncation_example.csv
Writes: paper/generated/figures/04_h2_truncation.pdf
        paper/generated/figures/04_h2_truncation.png
        paper/generated/figures/04_h2_truncation.numbers.csv

Sidecar exposes the same numbers under the fig.04_h2_truncation stem for
\\result{fig.04_h2_truncation}{...} citations in the §6.2 caption.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

THIS_SCRIPT = "paper/figures_src/04_h2_truncation.py"


def load_numbers(csv_path: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    with csv_path.open(newline="") as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    reader = csv.DictReader(lines)
    for r in reader:
        out[r["metric"]] = int(r["value"])
    return out


def render_figure(nums: dict[str, int], out_pdf: Path, out_png: Path) -> None:
    plt.rcParams.update({
        "font.family": "serif",
        "font.size": 9,
        "axes.labelsize": 9,
        "axes.titlesize": 10,
        "xtick.labelsize": 8,
        "ytick.labelsize": 9,
        "pdf.fonttype": 42,
    })

    baseline = nums["baseline_chars"]
    cap = nums["exec_command_cap"]
    onlycode = nums["onlycode_chars"]
    trunc_tokens = nums["truncation_tokens"]

    fig, ax = plt.subplots(figsize=(3.4, 2.0))

    bar_h = 0.55
    y_baseline, y_onlycode = 1.0, 0.0

    ax.barh(y_baseline, cap, height=bar_h,
            color="#cfcfcf", edgecolor="black", linewidth=0.6, zorder=2)
    ax.add_patch(Rectangle(
        (cap, y_baseline - bar_h / 2), baseline - cap, bar_h,
        facecolor="#c44a4a", edgecolor="black", linewidth=0.6, zorder=2,
    ))

    ax.barh(y_onlycode, onlycode, height=bar_h,
            color="#3a7a4a", edgecolor="black", linewidth=0.6, zorder=2)

    ax.axvline(cap, color="black", linewidth=0.9, linestyle="--", zorder=3)
    ax.annotate(
        f"cap = {cap:,} chars",
        xy=(cap, y_baseline + bar_h / 2 + 0.05),
        xytext=(cap - 1500, y_baseline + bar_h / 2 + 0.35),
        fontsize=7, ha="right",
        arrowprops=dict(arrowstyle="-", color="black", linewidth=0.5),
    )

    ax.text(
        cap + (baseline - cap) / 2, y_baseline,
        f"+{trunc_tokens:,}\ntokens\ntruncated",
        ha="center", va="center", fontsize=6, color="white", style="italic",
        zorder=4,
    )

    ax.text(baseline + 800, y_baseline, f"{baseline:,}",
            ha="left", va="center", fontsize=8)
    ax.text(onlycode + 800, y_onlycode, f"{onlycode:,}",
            ha="left", va="center", fontsize=8)

    ax.set_yticks([y_onlycode, y_baseline])
    ax.set_yticklabels([
        "code-only:\nsingle-pattern grep",
        "baseline:\nbroad keyword sweep",
    ])
    ax.set_xlabel("Per-call output (characters)")
    ax.set_xlim(0, baseline + 6500)
    ax.set_ylim(-0.6, 1.85)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(axis="y", length=0)

    fig.tight_layout(pad=0.3)
    fig.savefig(out_pdf, format="pdf", bbox_inches="tight")
    fig.savefig(out_png, format="png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def write_sidecar(nums: dict[str, int], out_path: Path, source_data: str) -> None:
    rows = [
        ("baseline_chars",     str(nums["baseline_chars"]),     "char_count"),
        ("exec_command_cap",   str(nums["exec_command_cap"]),   "char_count"),
        ("onlycode_chars",     str(nums["onlycode_chars"]),     "char_count"),
        ("truncation_tokens",  str(nums["truncation_tokens"]),  "token_count"),
        ("ratio_baseline_onlycode",
         f"{nums['baseline_chars'] / nums['onlycode_chars']:.4f}", "ratio"),
    ]
    with out_path.open("w", newline="") as f:
        f.write(f"# generator: {THIS_SCRIPT}\n")
        f.write(f"# source_data: {source_data}\n")
        w = csv.writer(f)
        w.writerow(["label", "value", "role"])
        for r in rows:
            w.writerow(r)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--paper-dir", type=Path,
                    default=Path(__file__).resolve().parents[1])
    args = ap.parse_args()
    paper_dir: Path = args.paper_dir

    csv_path = paper_dir / "data" / "h2_truncation_example.csv"
    out_dir = paper_dir / "generated" / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / "04_h2_truncation.pdf"
    png_path = out_dir / "04_h2_truncation.png"
    sidecar_path = out_dir / "04_h2_truncation.numbers.csv"

    nums = load_numbers(csv_path)
    render_figure(nums, pdf_path, png_path)
    write_sidecar(nums, sidecar_path,
                  source_data=str(csv_path.relative_to(paper_dir.parent)))
    print(f"  wrote {pdf_path}")
    print(f"  wrote {png_path}")
    print(f"  wrote {sidecar_path}")


if __name__ == "__main__":
    main()
