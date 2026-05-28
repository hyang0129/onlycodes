"""§5.4 + §6.3 numbers: per-cell agreement-matrix counts and the
unanimous-pass-conditional headline contrast.

Reads `paper/data/raw/all_results.csv` (collected by
`scripts/collect_results.py`) and emits two CSVs that the paper build pipeline
picks up automatically via `\\result{...}` macros:

  * `paper/data/agreement_matrix.csv` — per-cell unanimous / split counts,
    split-structure diagnostics, seed-noise sensitivity, plus a single
    `_all:_all` row for global scalars (cache-floor stability metrics, min
    unanimous-strict pct).
  * `paper/data/headline_unanimous.csv` — full-set vs unanimous-pass-subset
    contrast metrics for each (benchmark, agent) cell, using the same `code-arm
    minus cheapest-rival` direction as Table 1. Cost-adj on the unanimous-pass
    subset is computed with the **cache-floor median recomputed on the
    subset** (matching `scripts/collect_results.py:_apply_cache_floor_adjustment`).

Methodology:
  - Agreement classification: STRICT (9/9 PASS or 0/9 FAIL) and MAJORITY
    (every arm's pass-rate >= 2/3 agreeing on the P/F label).
  - Cache-floor recompute: per (benchmark, seed, agent, arm) group, median of
    first_call_cache_read over rows where cache_read > 0 (warm subset).
  - Adjusted cost = cost_usd - moved * (input_rate - cache_read_rate) / 1e6
    with moved = max(median_floor, first_call_cache_read) - first_call_cache_read.
  - Paired stats: per-instance Δ across available seeds; Wilcoxon signed-rank
    two-sided + paired-t (illustrative).

Prices match `scripts/parse_run.py:194` (Claude sonnet-4-6) and
`swebench/codex_prices.toml` (Codex gpt-5.5).

Run from repo root:
    python paper/data/scripts/q3_unanimous_pass.py            # report only
    python paper/data/scripts/q3_unanimous_pass.py --csv      # report + CSVs
"""
from __future__ import annotations
import argparse, csv, datetime, math, statistics, subprocess
from collections import defaultdict
from pathlib import Path

try:
    from scipy.stats import wilcoxon
    HAVE_SCIPY = True
except ImportError:
    HAVE_SCIPY = False

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(__file__).resolve().parents[1]
RAW_CSV = DATA_DIR / "raw" / "all_results.csv"
THIS_SCRIPT = Path(__file__).relative_to(REPO_ROOT)

CLAUDE_INPUT_RATE = 3.00       # USD per 1M
CLAUDE_CACHE_READ_RATE = 0.30
CODEX_INPUT_RATE = 5.00
CODEX_CACHE_READ_RATE = 0.50

CLAUDE_GAP_PER_TOK = (CLAUDE_INPUT_RATE - CLAUDE_CACHE_READ_RATE) / 1_000_000.0
CODEX_GAP_PER_TOK = (CODEX_INPUT_RATE - CODEX_CACHE_READ_RATE) / 1_000_000.0


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


def _write_csv(path: Path, header_lines: list[str], fieldnames: list[str], rows: list[dict]):
    with path.open("w", newline="") as f:
        for line in header_lines:
            f.write(line + "\n")
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        if math.isnan(v):
            return ""
        return repr(v)
    return str(v)


def _safe_int(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _safe_float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def load_rows(path: Path) -> list[dict]:
    out = []
    with path.open(newline="") as f:
        for r in csv.DictReader(f):
            out.append({
                "benchmark": r["benchmark"],
                "agent": r["agent"],
                "arm": r["arm"],
                "seed": int(r["seed"]),
                "instance_id": r["instance_id"],
                "verdict": r["verdict"].strip(),
                "cost_usd": _safe_float(r["cost_usd"]),
                "first_call_input_tokens": _safe_int(r["first_call_input_tokens"]),
                "first_call_cache_read": _safe_int(r["first_call_cache_read"]),
                "input_tokens": _safe_int(r["input_tokens"]),
                "output_tokens": _safe_int(r["output_tokens"]),
            })
    return out


def arm_rates(trials: dict) -> dict:
    rates = defaultdict(list)
    for (arm, seed), v in trials.items():
        rates[arm].append(v)
    return {a: sum(vs) / len(vs) for a, vs in rates.items()}


def classify_strict(trials: dict) -> str:
    vs = list(trials.values())
    if all(v == 1 for v in vs): return "unanimous_pass"
    if all(v == 0 for v in vs): return "unanimous_fail"
    return "split"


def classify_majority(trials: dict, threshold: float = 2/3) -> str:
    rates = arm_rates(trials)
    labels = ["P" if r >= threshold else "F" for r in rates.values()]
    if all(l == "P" for l in labels): return "unanimous_pass"
    if all(l == "F" for l in labels): return "unanimous_fail"
    return "split"


def per_token_gap(agent: str) -> float:
    return CLAUDE_GAP_PER_TOK if agent == "claude" else CODEX_GAP_PER_TOK


def recompute_floors(subset: list[dict]) -> dict:
    """Group by (bench, seed, agent, arm); return median first_call_cache_read
    over warm rows (cache_read > 0). Mirrors collect_results.py."""
    g: dict = defaultdict(list)
    for r in subset:
        if r["first_call_cache_read"] is not None and r["first_call_cache_read"] > 0:
            g[(r["benchmark"], r["seed"], r["agent"], r["arm"])].append(r["first_call_cache_read"])
    return {k: int(statistics.median(v)) for k, v in g.items()}


def cost_adj(row: dict, floor: int) -> float | None:
    cost = row["cost_usd"]
    fi = row["first_call_input_tokens"]
    fc = row["first_call_cache_read"]
    if cost is None or fi is None or fc is None:
        return cost
    adj_cached = max(fc, min(floor, fi))
    moved = adj_cached - fc
    return cost - moved * per_token_gap(row["agent"])


# -----------------------------------------------------------------------------
# Agreement matrix builder
# -----------------------------------------------------------------------------

CELLS = [
    ("artifact", "claude"),
    ("artifact", "codex"),
    ("swebench", "claude"),
    ("swebench", "codex"),
]


def build_verdicts(rows: list[dict]) -> dict:
    v = defaultdict(dict)
    for r in rows:
        v[(r["benchmark"], r["agent"], r["instance_id"])][(r["arm"], r["seed"])] = (
            1 if r["verdict"] == "PASS" else 0
        )
    return v


def count_strictly_arm_specific(split_iids: list[tuple], verdicts: dict, bench: str, agent: str) -> int:
    """Splits where exactly one arm has any passes — the failure mode the §6 prediction worries about."""
    n = 0
    for iid in split_iids:
        rates = arm_rates(verdicts[(bench, agent, iid)])
        nonzero = sum(1 for r in rates.values() if r > 0)
        if nonzero == 1:
            n += 1
    return n


def per_seed_agreement(trials: dict) -> float:
    seeds: dict = defaultdict(list)
    for (arm, seed), v in trials.items():
        seeds[seed].append(v)
    agree = 0
    for vs in seeds.values():
        if all(v == 1 for v in vs) or all(v == 0 for v in vs):
            agree += 1
    return agree / len(seeds) if seeds else 0.0


def seed_leave_one_out_flip_rate(trials_list: list[tuple]) -> float:
    """Fraction of instances whose STRICT classification changes under any
    leave-one-seed-out."""
    flips = 0
    for iid, t in trials_list:
        base = classify_strict(t)
        for excluded in (1, 2, 3):
            sub = {k: v for k, v in t.items() if k[1] != excluded}
            if classify_strict(sub) != base:
                flips += 1
                break
    return flips / len(trials_list) if trials_list else 0.0


def build_agreement_matrix(rows: list[dict]) -> tuple[list[dict], dict]:
    """Returns (per_cell_rows, global_scalars)."""
    verdicts = build_verdicts(rows)

    # Cache-floor stability check: compare full-set floor with strict and
    # majority subset floors. Per (benchmark, seed, agent, arm).
    floor_full = recompute_floors(rows)
    strict_iids = {k for k, t in verdicts.items() if classify_strict(t) == "unanimous_pass"}
    maj_iids = {k for k, t in verdicts.items() if classify_majority(t) == "unanimous_pass"}
    floor_strict = recompute_floors([r for r in rows
                                     if (r["benchmark"], r["agent"], r["instance_id"]) in strict_iids])
    floor_maj = recompute_floors([r for r in rows
                                  if (r["benchmark"], r["agent"], r["instance_id"]) in maj_iids])
    cache_floor_total = len(floor_full)
    cache_floor_unchanged_strict = sum(1 for k, v in floor_full.items() if floor_strict.get(k) == v)
    cache_floor_unchanged_majority = sum(1 for k, v in floor_full.items() if floor_maj.get(k) == v)
    cache_floor_max_diff_strict = max((abs(v - floor_strict.get(k, v)) for k, v in floor_full.items()), default=0)
    cache_floor_max_diff_majority = max((abs(v - floor_maj.get(k, v)) for k, v in floor_full.items()), default=0)

    per_cell_rows: list[dict] = []
    min_unanimous_strict_pct = 100.0
    min_unanimous_majority_pct = 100.0

    for bench, agent in CELLS:
        cell_iids = [(iid, v) for (b, a, iid), v in verdicts.items() if b == bench and a == agent]
        n = len(cell_iids)
        if n == 0:
            continue

        cat_strict = defaultdict(list)
        cat_maj = defaultdict(list)
        for iid, t in cell_iids:
            cat_strict[classify_strict(t)].append(iid)
            cat_maj[classify_majority(t)].append(iid)

        n_up_strict = len(cat_strict["unanimous_pass"])
        n_uf_strict = len(cat_strict["unanimous_fail"])
        n_sp_strict = len(cat_strict["split"])
        n_up_maj = len(cat_maj["unanimous_pass"])
        n_uf_maj = len(cat_maj["unanimous_fail"])
        n_sp_maj = len(cat_maj["split"])

        unanimous_strict_pct = 100.0 * (n_up_strict + n_uf_strict) / n
        unanimous_majority_pct = 100.0 * (n_up_maj + n_uf_maj) / n
        split_strict_pct = 100.0 * n_sp_strict / n
        split_majority_pct = 100.0 * n_sp_maj / n

        min_unanimous_strict_pct = min(min_unanimous_strict_pct, unanimous_strict_pct)
        min_unanimous_majority_pct = min(min_unanimous_majority_pct, unanimous_majority_pct)

        per_seed = sum(per_seed_agreement(t) for _, t in cell_iids) / n
        seed_flip = seed_leave_one_out_flip_rate(cell_iids)

        arm_specific_majority = count_strictly_arm_specific(
            cat_maj["split"], verdicts, bench, agent
        )

        per_cell_rows.append({
            "benchmark": bench,
            "agent": agent,
            "n_instances": n,
            "unanimous_strict_pct": round(unanimous_strict_pct, 2),
            "unanimous_strict_pass_n": n_up_strict,
            "unanimous_strict_fail_n": n_uf_strict,
            "split_strict_n": n_sp_strict,
            "split_strict_pct": round(split_strict_pct, 2),
            "unanimous_majority_pct": round(unanimous_majority_pct, 2),
            "unanimous_majority_pass_n": n_up_maj,
            "unanimous_majority_fail_n": n_uf_maj,
            "split_majority_n": n_sp_maj,
            "split_majority_pct": round(split_majority_pct, 2),
            "per_seed_agreement_pct": round(100.0 * per_seed, 2),
            "seed_flip_rate_pct": round(100.0 * seed_flip, 2),
            "strictly_arm_specific_split_n": arm_specific_majority,
        })

    global_scalars = {
        "cache_floor_total_groups": cache_floor_total,
        "cache_floor_unchanged_strict": cache_floor_unchanged_strict,
        "cache_floor_unchanged_majority": cache_floor_unchanged_majority,
        "cache_floor_max_diff_tokens_strict": cache_floor_max_diff_strict,
        "cache_floor_max_diff_tokens_majority": cache_floor_max_diff_majority,
        "min_unanimous_strict_pct": round(min_unanimous_strict_pct, 2),
        "min_unanimous_majority_pct": round(min_unanimous_majority_pct, 2),
    }
    return per_cell_rows, global_scalars


# -----------------------------------------------------------------------------
# Headline-unanimous contrast builder
# -----------------------------------------------------------------------------

HEADLINE_CONTRASTS = [
    ("artifact", "claude", "code_only", "bash_only"),
    ("artifact", "codex",  "code_only", "bash_only"),
    ("swebench", "claude", "onlycode",  "baseline"),
    ("swebench", "codex",  "onlycode",  "baseline"),
]
METRICS = ["cost_adj", "input_tokens", "output_tokens", "pass"]


def paired_stats(deltas: list[float]) -> dict:
    n = len(deltas)
    if n < 2:
        return {"n": n, "mean": float("nan"), "se": float("nan"), "t": float("nan"), "wilcoxon_p": float("nan")}
    m = statistics.mean(deltas)
    sd = statistics.stdev(deltas)
    se = sd / n**0.5
    t = m / se if se else float("nan")
    if HAVE_SCIPY:
        try:
            w = wilcoxon(deltas, alternative="two-sided", zero_method="wilcox", correction=False)
            wp = float(w.pvalue)
        except ValueError:
            wp = float("nan")
    else:
        wp = float("nan")
    return {"n": n, "mean": m, "se": se, "t": t, "wilcoxon_p": wp}


def per_arm_per_instance(subset: list[dict], adj_cost: dict, metric: str) -> dict:
    """Returns arm → instance_id → mean across available seeds."""
    bucket: dict = defaultdict(lambda: defaultdict(list))
    for r in subset:
        if metric == "cost_adj":
            v = adj_cost.get((r["benchmark"], r["seed"], r["agent"], r["arm"],
                              r["instance_id"]))
        elif metric == "pass":
            v = 1.0 if r["verdict"] == "PASS" else 0.0
        elif metric == "input_tokens":
            v = r["input_tokens"]
        elif metric == "output_tokens":
            v = r["output_tokens"]
        else:
            v = None
        if v is None:
            continue
        bucket[r["arm"]][r["instance_id"]].append(float(v))
    return {arm: {iid: statistics.mean(vs) for iid, vs in by.items()}
            for arm, by in bucket.items()}


def compute_contrasts(
    rows: list[dict], iid_filter: set[tuple] | None
) -> dict:
    """For each contrast (cell × metric × code-vs-rival), compute paired stats.

    iid_filter: if not None, restrict to instances (benchmark, agent, iid) in
    the set. The cache-floor median is recomputed on the (possibly filtered)
    subset, mirroring scripts/collect_results.py.
    """
    subset = (rows if iid_filter is None
              else [r for r in rows
                    if (r["benchmark"], r["agent"], r["instance_id"]) in iid_filter])

    floors = recompute_floors(subset)
    adj = {}
    for r in subset:
        key = (r["benchmark"], r["seed"], r["agent"], r["arm"], r["instance_id"])
        adj[key] = cost_adj(r, floors.get((r["benchmark"], r["seed"], r["agent"], r["arm"]), 0))

    out = {}
    for bench, agent, code_arm, rival in HEADLINE_CONTRASTS:
        cell_rows = [r for r in subset if r["benchmark"] == bench and r["agent"] == agent]
        for metric in METRICS:
            per_arm = per_arm_per_instance(cell_rows, adj, metric)
            code_map = per_arm.get(code_arm, {})
            rival_map = per_arm.get(rival, {})
            iids = sorted(set(code_map.keys()) & set(rival_map.keys()))
            deltas = [code_map[i] - rival_map[i] for i in iids]
            mean_rival = statistics.mean(rival_map.values()) if rival_map else float("nan")
            ps = paired_stats(deltas)
            out[(bench, agent, code_arm, rival, metric)] = {
                **ps,
                "mean_rival": mean_rival,
            }
    return out, floors


def build_headline_unanimous(rows: list[dict]) -> list[dict]:
    verdicts = build_verdicts(rows)
    maj_iids = {k for k, t in verdicts.items() if classify_majority(t) == "unanimous_pass"}
    strict_iids = {k for k, t in verdicts.items() if classify_strict(t) == "unanimous_pass"}

    full, _ = compute_contrasts(rows, None)
    uni_maj, _ = compute_contrasts(rows, maj_iids)
    uni_strict, _ = compute_contrasts(rows, strict_iids)

    out_rows = []
    for bench, agent, code_arm, rival in HEADLINE_CONTRASTS:
        for metric in METRICS:
            key = (bench, agent, code_arm, rival, metric)
            f = full[key]; um = uni_maj[key]; us = uni_strict[key]
            # For pass metric, report Δ in pp. For others, report relative %.
            def rel_pct(d: dict) -> float:
                if metric == "pass":
                    return d["mean"] * 100.0
                if d["mean_rival"] and not math.isnan(d["mean_rival"]) and d["mean_rival"] != 0:
                    return 100.0 * d["mean"] / d["mean_rival"]
                return float("nan")
            out_rows.append({
                "benchmark": bench,
                "agent": agent,
                "contrast": f"{code_arm}-vs-{rival}",
                "metric": metric,
                # Full set
                "full_mean_delta_pct": round(rel_pct(f), 4) if not math.isnan(rel_pct(f)) else None,
                "full_mean_delta_abs": _fmt(f["mean"]),
                "full_mean_rival": _fmt(f["mean_rival"]),
                "full_se": _fmt(f["se"]),
                "full_t": _fmt(f["t"]),
                "full_wilcoxon_p": _fmt(f["wilcoxon_p"]),
                "full_n": f["n"],
                # Unanimous-pass MAJORITY
                "unanimous_majority_mean_delta_pct": round(rel_pct(um), 4) if not math.isnan(rel_pct(um)) else None,
                "unanimous_majority_mean_delta_abs": _fmt(um["mean"]),
                "unanimous_majority_t": _fmt(um["t"]),
                "unanimous_majority_wilcoxon_p": _fmt(um["wilcoxon_p"]),
                "unanimous_majority_n": um["n"],
                # Unanimous-pass STRICT
                "unanimous_strict_mean_delta_pct": round(rel_pct(us), 4) if not math.isnan(rel_pct(us)) else None,
                "unanimous_strict_mean_delta_abs": _fmt(us["mean"]),
                "unanimous_strict_t": _fmt(us["t"]),
                "unanimous_strict_wilcoxon_p": _fmt(us["wilcoxon_p"]),
                "unanimous_strict_n": us["n"],
            })
    return out_rows


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def emit_csvs(rows, out_dir: Path):
    per_cell, global_scalars = build_agreement_matrix(rows)

    # Build agreement_matrix.csv: per-cell rows + one _all:_all row for global scalars.
    am_fields = [
        "benchmark", "agent",
        "n_instances",
        "unanimous_strict_pct", "unanimous_strict_pass_n", "unanimous_strict_fail_n",
        "split_strict_n", "split_strict_pct",
        "unanimous_majority_pct", "unanimous_majority_pass_n", "unanimous_majority_fail_n",
        "split_majority_n", "split_majority_pct",
        "per_seed_agreement_pct", "seed_flip_rate_pct",
        "strictly_arm_specific_split_n",
        # Global scalars (only populated on _all:_all row)
        "min_unanimous_strict_pct", "min_unanimous_majority_pct",
        "cache_floor_total_groups",
        "cache_floor_unchanged_strict", "cache_floor_unchanged_majority",
        "cache_floor_max_diff_tokens_strict", "cache_floor_max_diff_tokens_majority",
    ]
    am_rows = []
    for r in per_cell:
        full = {k: r.get(k, "") for k in am_fields}
        am_rows.append(full)
    am_rows.append({
        "benchmark": "_all", "agent": "_all",
        "n_instances": "",
        "unanimous_strict_pct": "", "unanimous_strict_pass_n": "", "unanimous_strict_fail_n": "",
        "split_strict_n": "", "split_strict_pct": "",
        "unanimous_majority_pct": "", "unanimous_majority_pass_n": "", "unanimous_majority_fail_n": "",
        "split_majority_n": "", "split_majority_pct": "",
        "per_seed_agreement_pct": "", "seed_flip_rate_pct": "",
        "strictly_arm_specific_split_n": "",
        "min_unanimous_strict_pct": global_scalars["min_unanimous_strict_pct"],
        "min_unanimous_majority_pct": global_scalars["min_unanimous_majority_pct"],
        "cache_floor_total_groups": global_scalars["cache_floor_total_groups"],
        "cache_floor_unchanged_strict": global_scalars["cache_floor_unchanged_strict"],
        "cache_floor_unchanged_majority": global_scalars["cache_floor_unchanged_majority"],
        "cache_floor_max_diff_tokens_strict": global_scalars["cache_floor_max_diff_tokens_strict"],
        "cache_floor_max_diff_tokens_majority": global_scalars["cache_floor_max_diff_tokens_majority"],
    })

    _write_csv(
        out_dir / "agreement_matrix.csv",
        _provenance_header(
            key_schema="benchmark:agent",
            default_precision=2,
            description=(
                "Per-cell agreement-matrix counts under STRICT (9/9 trials) and MAJORITY "
                "(per-arm pass-rate >= 2/3) definitions. The _all:_all row carries global "
                "scalars (min unanimous pct across cells, cache-floor stability counts: total "
                "and unchanged groups out of (benchmark, seed, agent, arm) tuples)."
            ),
        ),
        am_fields,
        am_rows,
    )

    # headline_unanimous.csv
    hu_rows = build_headline_unanimous(rows)
    hu_fields = [
        "benchmark", "agent", "contrast", "metric",
        "full_mean_delta_pct", "full_mean_delta_abs", "full_mean_rival",
        "full_se", "full_t", "full_wilcoxon_p", "full_n",
        "unanimous_majority_mean_delta_pct", "unanimous_majority_mean_delta_abs",
        "unanimous_majority_t", "unanimous_majority_wilcoxon_p", "unanimous_majority_n",
        "unanimous_strict_mean_delta_pct", "unanimous_strict_mean_delta_abs",
        "unanimous_strict_t", "unanimous_strict_wilcoxon_p", "unanimous_strict_n",
    ]
    _write_csv(
        out_dir / "headline_unanimous.csv",
        _provenance_header(
            key_schema="benchmark:agent:contrast:metric",
            default_precision=4,
            description=(
                "Full-set vs unanimous-pass-subset paired contrasts in the Table 1 "
                "code-arm-vs-cheapest-rival layout. Cost-adj on the unanimous-pass subset "
                "uses the cache-floor median recomputed on that subset per the "
                "scripts/collect_results.py:_apply_cache_floor_adjustment methodology. "
                "_mean_delta_pct is relative % vs rival for cost/input/output metrics; "
                "for the 'pass' metric it is Δ in percentage points (mean * 100). "
                "wilcoxon_p is paired Wilcoxon signed-rank two-sided."
            ),
        ),
        hu_fields,
        hu_rows,
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", action="store_true", help="Emit CSVs alongside the human-readable report.")
    args = ap.parse_args()

    if not RAW_CSV.exists():
        raise SystemExit(f"missing input: {RAW_CSV}")

    rows = load_rows(RAW_CSV)
    print(f"loaded {len(rows)} rows from {RAW_CSV.relative_to(REPO_ROOT)}")

    per_cell, global_scalars = build_agreement_matrix(rows)
    print("\n## Agreement matrix (per-cell)")
    for r in per_cell:
        print(f"  {r['benchmark']:10s}/{r['agent']:6s}  n={r['n_instances']:>3d}  "
              f"strict_unanimous={r['unanimous_strict_pct']:>6.2f}%  "
              f"majority_unanimous={r['unanimous_majority_pct']:>6.2f}%  "
              f"per_seed_agree={r['per_seed_agreement_pct']:>6.2f}%  "
              f"seed_flip={r['seed_flip_rate_pct']:>5.2f}%  "
              f"arm_specific_splits={r['strictly_arm_specific_split_n']}")
    print("\n## Global scalars")
    for k, v in global_scalars.items():
        print(f"  {k:42s} = {v}")

    hu_rows = build_headline_unanimous(rows)
    print("\n## Headline-unanimous contrasts (cost_adj only)")
    def _f(s, default=float("nan")):
        try: return float(s)
        except (TypeError, ValueError): return default
    for r in [x for x in hu_rows if x["metric"] == "cost_adj"]:
        wp = _f(r["full_wilcoxon_p"])
        wp_str = f"{wp:.3e}" if not math.isnan(wp) else "n/a"
        print(f"  {r['benchmark']:10s}/{r['agent']:6s}  {r['contrast']:25s}  "
              f"full Δ%={r['full_mean_delta_pct']:>+7.2f}  (t={_f(r['full_t']):+.2f}, "
              f"p={wp_str}, n={r['full_n']})    "
              f"uni-maj Δ%={r['unanimous_majority_mean_delta_pct']:>+7.2f}  "
              f"(t={_f(r['unanimous_majority_t']):+.2f}, n={r['unanimous_majority_n']})")
    if not HAVE_SCIPY:
        print("\n  [note] scipy not available; wilcoxon_p columns are empty. "
              "Install scipy and re-run to populate them.")

    if args.csv:
        emit_csvs(rows, DATA_DIR)
        print(f"\nwrote {DATA_DIR / 'agreement_matrix.csv'}")
        print(f"wrote {DATA_DIR / 'headline_unanimous.csv'}")


if __name__ == "__main__":
    main()
