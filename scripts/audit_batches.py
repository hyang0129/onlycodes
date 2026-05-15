#!/usr/bin/env python3
"""Audit completion of D1-D5 batches across the 3 seed dirs.

For each (seed, batch, instance, arm) checks for the presence of
`<instance_id>_<arm>_run1.jsonl` and its `_test.txt` sibling under
runs/swebench/full_run_seed_<N>/.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs" / "swebench"

ARMS = ("baseline", "onlycode", "bash_only")
SEEDS = (1, 2, 3)

BATCHES: dict[str, list[str]] = {
    "D1": [
        "scikit-learn__scikit-learn-10427", "scikit-learn__scikit-learn-10803",
        "scikit-learn__scikit-learn-11206", "scikit-learn__scikit-learn-11596",
        "scikit-learn__scikit-learn-12704", "scikit-learn__scikit-learn-13013",
        "scikit-learn__scikit-learn-13283", "scikit-learn__scikit-learn-13496",
    ],
    "D2": [
        "scikit-learn__scikit-learn-13864", "scikit-learn__scikit-learn-14125",
        "scikit-learn__scikit-learn-14710", "scikit-learn__scikit-learn-15094",
        "scikit-learn__scikit-learn-24677", "scikit-learn__scikit-learn-25694",
        "scikit-learn__scikit-learn-3840",
    ],
    "D3": [
        "matplotlib__matplotlib-13859", "matplotlib__matplotlib-19763",
        "matplotlib__matplotlib-21042", "matplotlib__matplotlib-22767",
        "matplotlib__matplotlib-23088", "matplotlib__matplotlib-23476",
        "matplotlib__matplotlib-24177", "matplotlib__matplotlib-24637",
        "matplotlib__matplotlib-25126", "matplotlib__matplotlib-25442",
        "matplotlib__matplotlib-25772", "matplotlib__matplotlib-26160",
    ],
    "D4": [
        "pydata__xarray-2905", "pydata__xarray-3520", "pydata__xarray-4075",
        "pydata__xarray-4629", "pydata__xarray-4911", "pydata__xarray-5455",
        "pydata__xarray-6601", "pydata__xarray-7003",
        "astropy__astropy-12962", "astropy__astropy-13842", "astropy__astropy-6938",
    ],
    "D5": [
        "sympy__sympy-11232", "sympy__sympy-13259", "sympy__sympy-14180",
        "sympy__sympy-15976", "sympy__sympy-17318", "sympy__sympy-19016",
        "sympy__sympy-21596",
        "mwaskom__seaborn-2389", "mwaskom__seaborn-2813", "mwaskom__seaborn-2946",
        "mwaskom__seaborn-3069", "mwaskom__seaborn-3202",
    ],
}


def triple_done(seed_dir: Path, instance: str, arm: str) -> bool:
    jsonl = seed_dir / f"{instance}_{arm}_run1.jsonl"
    test = seed_dir / f"{instance}_{arm}_run1_test.txt"
    return jsonl.exists() and test.exists()


def main(verbose: bool = False) -> int:
    print(f"{'Batch':<5}  {'Seed':<6}  {'Done':>7}  {'Total':>5}  Missing")
    print("-" * 78)
    grand_done = grand_total = 0
    missing_per_seed: dict[int, list[str]] = {s: [] for s in SEEDS}
    for batch, instances in BATCHES.items():
        total_arms = len(instances) * len(ARMS)
        for seed in SEEDS:
            seed_dir = RUNS / f"full_run_seed_{seed}"
            missing: list[str] = []
            done = 0
            for inst in instances:
                for arm in ARMS:
                    if triple_done(seed_dir, inst, arm):
                        done += 1
                    else:
                        missing.append(f"{inst}:{arm}")
            grand_done += done
            grand_total += total_arms
            missing_per_seed[seed].extend(missing)
            tag = "OK" if not missing else f"{len(missing)} miss"
            print(f"{batch:<5}  seed_{seed}  {done:>3}/{total_arms:<3}  {total_arms:>5}  {tag}")
        print()
    print("-" * 78)
    print(f"TOTAL: {grand_done}/{grand_total} arm-runs complete "
          f"({grand_done * 100 // grand_total}%)")

    if verbose:
        print()
        for seed in SEEDS:
            miss = missing_per_seed[seed]
            print(f"\nseed_{seed} missing ({len(miss)}):")
            for m in miss:
                print(f"  - {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main(verbose="-v" in sys.argv or "--verbose" in sys.argv))
