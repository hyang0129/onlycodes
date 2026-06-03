#!/usr/bin/env python3
"""Spine significance report (#299, WS-A closing step).

Consumes the modification-regime spine run dirs (one per seed) for a single
agent and emits, per non-baseline arm, the **cache-adjusted** cost contrast vs
``baseline`` with a paired-bootstrap CI + p-value, a distribution-free Wilcoxon
cross-check, an optional TOST equivalence verdict (the "cleanly null under
adequate power" branch), and a paired McNemar **pass-rate guard** so the cost
comparison isn't confounded by a capability gap.

This is the artifact that answers #299's "done when": the SWE-bench/Claude cost
contrast is **significant** or **cleanly null** under adequate power.

Cost definition is the same first-call cache-adjusted cost used by the paper's
headline cell (``scripts/cost_first_call_adjust.adjusted_costs``) and by the
power analysis (#307) — one source of truth across power and significance.

Seeds are aggregated per (instance, arm) by the **mean** adjusted cost before
the ratio (paired log-contrast across instances); pass/fail is aggregated by
**majority vote** across seeds for the McNemar guard.

Usage:
  scripts/spine_significance.py \
      --agent claude \
      --runs runs/swebench/verified_spine_claude_seed_1 \
             runs/swebench/verified_spine_claude_seed_2 \
             runs/swebench/verified_spine_claude_seed_3 \
      [--filter @sets/verified-buildable.txt] \
      [--reference baseline] [--treatments onlycode,bash_only] \
      [--bound-pct 10] [--n-boot 10000] [--seed 0] \
      [--out-prefix runs/swebench/_analysis/spine/claude_swe]

Run once per agent (claude, codex); filter to a regime subset if a run dir
mixes regimes.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Put the repo root (for the `swebench` package) and scripts/ (for the sibling
# cost_first_call_adjust module) on the path so this runs as a plain script.
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

from cost_first_call_adjust import adjusted_costs  # noqa: E402

from swebench.analyze.summary import _parse_results  # noqa: E402
from swebench.contrast_stats import (  # noqa: E402
    equivalence_tost,
    mcnemar_from_passes,
    paired_cost_contrast,
)


def _resolve_filter(spec: str | None) -> set[str] | None:
    """Mirror swebench.run._parse_filter_ids: comma list or @file of IDs."""
    if not spec:
        return None
    spec = spec.strip()
    if spec.startswith("@"):
        path = Path(spec[1:]).expanduser()
        if not path.is_file():
            sys.exit(f"ERROR: --filter file not found: {path}")
        ids = set()
        for raw in path.read_text().splitlines():
            line = raw.split("#", 1)[0].strip()
            if line:
                ids.add(line)
        return ids
    return {s.strip() for s in spec.split(",") if s.strip()}


def load_cell(
    run_dirs: list[Path], mode: str, keep: set[str] | None
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, bool]]]:
    """Aggregate seed run dirs into per-(arm, instance) cost + pass maps.

    Returns ``(mean_cost, majority_pass)`` where:
      * ``mean_cost[arm][instance]`` = mean cache-adjusted cost across all
        seed runs that produced a cost for that (arm, instance).
      * ``majority_pass[arm][instance]`` = True iff the instance PASSed on a
        majority of the seeds that yielded a PASS/FAIL verdict.
    """
    costs: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    passes: dict[str, dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))

    for rd in run_dirs:
        rd = Path(rd)
        if not rd.is_dir():
            sys.exit(f"ERROR: run dir not found: {rd}")
        bundle = adjusted_costs(rd, mode=mode)
        for r in bundle["per_row"]:
            iid = r["instance_id"]
            if keep is not None and iid not in keep:
                continue
            if r.get("adj_cost") is not None:
                costs[r["arm"]][iid].append(float(r["adj_cost"]))
        for ar in _parse_results(rd):
            if keep is not None and ar.instance_id not in keep:
                continue
            if ar.verdict in ("PASS", "FAIL"):
                passes[ar.arm][ar.instance_id].append(ar.verdict == "PASS")

    mean_cost = {
        arm: {iid: sum(v) / len(v) for iid, v in inst.items() if v}
        for arm, inst in costs.items()
    }
    majority_pass = {
        arm: {iid: (sum(v) / len(v) >= 0.5) for iid, v in inst.items() if v}
        for arm, inst in passes.items()
    }
    return mean_cost, majority_pass


def build_report(
    run_dirs: list[Path],
    *,
    agent: str,
    mode: str,
    reference: str,
    treatments: list[str],
    keep: set[str] | None,
    bound_pct: float,
    n_boot: int,
    alpha: float,
    seed: int,
) -> dict:
    mean_cost, majority_pass = load_cell(run_dirs, mode, keep)
    if reference not in mean_cost:
        sys.exit(f"ERROR: reference arm '{reference}' has no cost rows in the run dirs.")

    contrasts = []
    for arm in treatments:
        if arm not in mean_cost:
            continue
        contrast = paired_cost_contrast(
            mean_cost[arm], mean_cost[reference],
            n_boot=n_boot, alpha=alpha, seed=seed,
        )
        equiv = equivalence_tost(
            mean_cost[arm], mean_cost[reference],
            bound_pct=bound_pct, n_boot=n_boot, alpha=alpha, seed=seed,
        )
        mcn = mcnemar_from_passes(
            majority_pass.get(arm, {}), majority_pass.get(reference, {}),
        )
        contrasts.append({
            "treatment": arm,
            "reference": reference,
            "cost_contrast": contrast.as_dict(),
            "equivalence": equiv.as_dict(),
            "pass_rate_guard": mcn.as_dict(),
        })

    return {
        "agent": agent,
        "mode": mode,
        "reference": reference,
        "n_seeds": len(run_dirs),
        "run_dirs": [str(r) for r in run_dirs],
        "n_filter": (len(keep) if keep is not None else None),
        "bound_pct": bound_pct,
        "n_boot": n_boot,
        "alpha": alpha,
        "contrasts": contrasts,
    }


def _print_report(rep: dict) -> None:
    print("=" * 96)
    print(f"Spine significance — agent={rep['agent']}  seeds={rep['n_seeds']}  "
          f"reference={rep['reference']}"
          + (f"  filtered_to={rep['n_filter']} ids" if rep["n_filter"] else ""))
    print("=" * 96)
    if not rep["contrasts"]:
        print("(no non-baseline arms found in the run dirs)")
        return
    for c in rep["contrasts"]:
        cc = c["cost_contrast"]
        eq = c["equivalence"]
        mc = c["pass_rate_guard"]
        verdict = (
            "SIGNIFICANT" if cc["significant"]
            else ("EQUIVALENT (clean null)" if eq["equivalent"]
                  else "INCONCLUSIVE (NS, not equivalent)")
        )
        print(f"\n  {c['treatment']} vs {c['reference']}  [{verdict}]")
        print(f"    cost  : {cc['pct_effect']:+.1f}%  "
              f"CI[{cc['ci_pct_lo']:+.1f}%, {cc['ci_pct_hi']:+.1f}%]  "
              f"p_boot={cc['p_bootstrap']:.4g}  "
              f"p_wilcoxon={cc['p_wilcoxon'] if cc['p_wilcoxon'] is None else round(cc['p_wilcoxon'],4)}  "
              f"n={cc['n']} (dropped {cc['n_dropped']})")
        print(f"    TOST  : {'within' if eq['equivalent'] else 'NOT within'} "
              f"±{rep['bound_pct']:.0f}%  "
              f"90%CI[{eq['tost_ci_pct_lo']:+.1f}%, {eq['tost_ci_pct_hi']:+.1f}%]")
        print(f"    pass  : {mc['pass_rate_treatment']*100:.1f}% vs "
              f"{mc['pass_rate_reference']*100:.1f}%  "
              f"McNemar p={mc['mcnemar_p']:.4g}  "
              f"(discordant {mc['discordant_treatment_only']}/{mc['discordant_reference_only']})")


def _write_outputs(rep: dict, out_prefix: str) -> None:
    out = Path(out_prefix)
    out.parent.mkdir(parents=True, exist_ok=True)
    json_path = out.with_suffix(".json")
    json_path.write_text(json.dumps(rep, indent=2))
    csv_path = out.with_suffix(".csv")
    fieldnames = [
        "agent", "treatment", "reference", "n", "n_dropped",
        "pct_effect", "ci_pct_lo", "ci_pct_hi", "p_bootstrap", "p_wilcoxon",
        "significant", "equivalent", "tost_ci_pct_lo", "tost_ci_pct_hi",
        "pass_rate_treatment", "pass_rate_reference", "mcnemar_p",
    ]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for c in rep["contrasts"]:
            cc, eq, mc = c["cost_contrast"], c["equivalence"], c["pass_rate_guard"]
            w.writerow({
                "agent": rep["agent"], "treatment": c["treatment"],
                "reference": c["reference"], "n": cc["n"], "n_dropped": cc["n_dropped"],
                "pct_effect": cc["pct_effect"], "ci_pct_lo": cc["ci_pct_lo"],
                "ci_pct_hi": cc["ci_pct_hi"], "p_bootstrap": cc["p_bootstrap"],
                "p_wilcoxon": cc["p_wilcoxon"], "significant": cc["significant"],
                "equivalent": eq["equivalent"], "tost_ci_pct_lo": eq["tost_ci_pct_lo"],
                "tost_ci_pct_hi": eq["tost_ci_pct_hi"],
                "pass_rate_treatment": mc["pass_rate_treatment"],
                "pass_rate_reference": mc["pass_rate_reference"],
                "mcnemar_p": mc["mcnemar_p"],
            })
    print(f"\nWrote {json_path} and {csv_path}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agent", required=True, help="Label for the cell (e.g. claude, codex).")
    ap.add_argument("--runs", nargs="+", required=True, type=Path,
                    help="Seed run dirs (one per seed).")
    ap.add_argument("--mode", choices=["auto", "codex", "claude"], default="auto")
    ap.add_argument("--reference", default="baseline")
    ap.add_argument("--treatments", default="onlycode,bash_only",
                    help="Comma-separated non-baseline arms to contrast vs --reference.")
    ap.add_argument("--filter", dest="filter_spec", default=None,
                    help="Restrict to instance IDs: comma list or @file (e.g. a regime subset).")
    ap.add_argument("--bound-pct", type=float, default=10.0,
                    help="TOST equivalence bound in percent (default ±10%%).")
    ap.add_argument("--n-boot", type=int, default=10000)
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out-prefix", default=None,
                    help="Write <prefix>.json and <prefix>.csv "
                         "(default: runs/swebench/_analysis/spine/<agent>).")
    args = ap.parse_args(argv)

    keep = _resolve_filter(args.filter_spec)
    treatments = [t.strip() for t in args.treatments.split(",") if t.strip()]
    rep = build_report(
        args.runs, agent=args.agent, mode=args.mode, reference=args.reference,
        treatments=treatments, keep=keep, bound_pct=args.bound_pct,
        n_boot=args.n_boot, alpha=args.alpha, seed=args.seed,
    )
    _print_report(rep)
    out_prefix = args.out_prefix or str(
        REPO_ROOT / "runs" / "swebench" / "_analysis" / "spine" / args.agent
    )
    _write_outputs(rep, out_prefix)


if __name__ == "__main__":
    main()
