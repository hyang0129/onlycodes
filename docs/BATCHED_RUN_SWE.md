# Batched SWE-bench Mini Run

100 problems split across two sets and 9 batches. Each seed is an independent full run in its own output dir. Three seeds are planned for variance estimation.

## Sets

| Set | Problems | Repos | Batches |
|---|---|---|---|
| swebench-verified-mini | 50 | Django (25), Sphinx (25) | V1–V4 |
| swebench-datasci-mini | 50 | scikit-learn (15), matplotlib (12), xarray (8), sympy (7), seaborn (5), astropy (3) | D1–D5 |

## Seeds

| Seed | Output dir | Status |
|---|---|---|
| seed_1 | `runs/swebench/full_run_seed_1/` | V1–V4 complete (50/100) |
| seed_2 | `runs/swebench/full_run_seed_2/` | not started |
| seed_3 | `runs/swebench/full_run_seed_3/` | not started |

## How it works

- Each seed gets its own `--output-dir` — independent runs, no cross-contamination.
- `--resume` (default on) skips any `(instance, arm, run)` triple that already has a result within a seed dir, so re-running a batch is safe.
- Same-repo batches share the OverlayFS cache, so sequential same-repo batches are faster than cross-repo ones.
- Arms: `baseline` (full tool suite), `onlycode` (execute_code MCP only), `bash_only` (Bash-only built-ins)
- **Always run with `--parallel 2`** — each instance runs 3 arms sequentially, but 2 instances can run concurrently without contention.

## Commands

```bash
cd /workspaces/hub_1/onlycodes
source .venv/bin/activate
export SWEBENCH_CACHE_ROOT=/tmp/swebench-cache
```

## Cache setup (one-time per machine)

`--use-cache` is on by default. Instances not in the cache fall back to a fresh
clone automatically, but the two heavy sklearn instances (24677, 25694) take
~18 min each to compile from scratch — warm them up before running D2.

```bash
# Already done on this machine (skip if /tmp/swebench-cache exists with both entries):
python -m swebench cache setup \
  --filter "scikit-learn__scikit-learn-24677,scikit-learn__scikit-learn-25694" \
  --concurrency 1
```

All other instances (Django, Sphinx, matplotlib, xarray, sympy, seaborn, astropy)
compile in under 2 min each and can be cached opportunistically or left to fall
back to the clone path:

```bash
# Optional — caches everything else for faster arm-to-arm resets:
python -m swebench cache setup --concurrency 4
```

---

## Seed 1 — `runs/swebench/full_run_seed_1/`

### Batch V1 — Django part 1 (13 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_1 \
  --parallel 2 \
  --filter "django__django-11790,django__django-11815,django__django-11848,django__django-11880,django__django-11885,django__django-11951,django__django-11964,django__django-11999,django__django-12039,django__django-12050,django__django-12143,django__django-12155,django__django-12193"
```

### Batch V2 — Django part 2 (12 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_1 \
  --parallel 2 \
  --filter "django__django-12209,django__django-12262,django__django-12273,django__django-12276,django__django-12304,django__django-12308,django__django-12325,django__django-12406,django__django-12708,django__django-12713,django__django-12774,django__django-9296"
```

### Batch V3 — Sphinx part 1 (13 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_1 \
  --parallel 2 \
  --filter "sphinx-doc__sphinx-10323,sphinx-doc__sphinx-10435,sphinx-doc__sphinx-10466,sphinx-doc__sphinx-10673,sphinx-doc__sphinx-11510,sphinx-doc__sphinx-7590,sphinx-doc__sphinx-7748,sphinx-doc__sphinx-7757,sphinx-doc__sphinx-7985,sphinx-doc__sphinx-8035,sphinx-doc__sphinx-8056,sphinx-doc__sphinx-8265,sphinx-doc__sphinx-8269"
```

### Batch V4 — Sphinx part 2 (12 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_1 \
  --parallel 2 \
  --filter "sphinx-doc__sphinx-8475,sphinx-doc__sphinx-8548,sphinx-doc__sphinx-8551,sphinx-doc__sphinx-8638,sphinx-doc__sphinx-8721,sphinx-doc__sphinx-9229,sphinx-doc__sphinx-9230,sphinx-doc__sphinx-9281,sphinx-doc__sphinx-9320,sphinx-doc__sphinx-9367,sphinx-doc__sphinx-9461,sphinx-doc__sphinx-9698"
```

### Batch D1 — scikit-learn part 1 (8 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_1 \
  --parallel 2 \
  --filter "scikit-learn__scikit-learn-10427,scikit-learn__scikit-learn-10803,scikit-learn__scikit-learn-11206,scikit-learn__scikit-learn-11596,scikit-learn__scikit-learn-12704,scikit-learn__scikit-learn-13013,scikit-learn__scikit-learn-13283,scikit-learn__scikit-learn-13496"
```

### Batch D2 — scikit-learn part 2 (7 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_1 \
  --parallel 2 \
  --filter "scikit-learn__scikit-learn-13864,scikit-learn__scikit-learn-14125,scikit-learn__scikit-learn-14710,scikit-learn__scikit-learn-15094,scikit-learn__scikit-learn-24677,scikit-learn__scikit-learn-25694,scikit-learn__scikit-learn-3840"
```

### Batch D3 — matplotlib (12 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_1 \
  --parallel 2 \
  --filter "matplotlib__matplotlib-13859,matplotlib__matplotlib-19763,matplotlib__matplotlib-21042,matplotlib__matplotlib-22767,matplotlib__matplotlib-23088,matplotlib__matplotlib-23476,matplotlib__matplotlib-24177,matplotlib__matplotlib-24637,matplotlib__matplotlib-25126,matplotlib__matplotlib-25442,matplotlib__matplotlib-25772,matplotlib__matplotlib-26160"
```

### Batch D4 — xarray + astropy (11 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_1 \
  --parallel 2 \
  --filter "pydata__xarray-2905,pydata__xarray-3520,pydata__xarray-4075,pydata__xarray-4629,pydata__xarray-4911,pydata__xarray-5455,pydata__xarray-6601,pydata__xarray-7003,astropy__astropy-12962,astropy__astropy-13842,astropy__astropy-6938"
```

### Batch D5 — sympy + seaborn (12 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_1 \
  --parallel 2 \
  --filter "sympy__sympy-11232,sympy__sympy-13259,sympy__sympy-14180,sympy__sympy-15976,sympy__sympy-17318,sympy__sympy-19016,sympy__sympy-21596,mwaskom__seaborn-2389,mwaskom__seaborn-2813,mwaskom__seaborn-2946,mwaskom__seaborn-3069,mwaskom__seaborn-3202"
```

### Seed 1 analysis

```bash
python -m swebench analyze summary \
  --results-dir runs/swebench/full_run_seed_1 \
  --out runs/swebench/full_run_seed_1/summary.csv
```

---

## Seed 2 — `runs/swebench/full_run_seed_2/`

### Batch V1 — Django part 1 (13 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_2 \
  --parallel 2 \
  --filter "django__django-11790,django__django-11815,django__django-11848,django__django-11880,django__django-11885,django__django-11951,django__django-11964,django__django-11999,django__django-12039,django__django-12050,django__django-12143,django__django-12155,django__django-12193"
```

### Batch V2 — Django part 2 (12 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_2 \
  --parallel 2 \
  --filter "django__django-12209,django__django-12262,django__django-12273,django__django-12276,django__django-12304,django__django-12308,django__django-12325,django__django-12406,django__django-12708,django__django-12713,django__django-12774,django__django-9296"
```

### Batch V3 — Sphinx part 1 (13 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_2 \
  --parallel 2 \
  --filter "sphinx-doc__sphinx-10323,sphinx-doc__sphinx-10435,sphinx-doc__sphinx-10466,sphinx-doc__sphinx-10673,sphinx-doc__sphinx-11510,sphinx-doc__sphinx-7590,sphinx-doc__sphinx-7748,sphinx-doc__sphinx-7757,sphinx-doc__sphinx-7985,sphinx-doc__sphinx-8035,sphinx-doc__sphinx-8056,sphinx-doc__sphinx-8265,sphinx-doc__sphinx-8269"
```

### Batch V4 — Sphinx part 2 (12 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_2 \
  --parallel 2 \
  --filter "sphinx-doc__sphinx-8475,sphinx-doc__sphinx-8548,sphinx-doc__sphinx-8551,sphinx-doc__sphinx-8638,sphinx-doc__sphinx-8721,sphinx-doc__sphinx-9229,sphinx-doc__sphinx-9230,sphinx-doc__sphinx-9281,sphinx-doc__sphinx-9320,sphinx-doc__sphinx-9367,sphinx-doc__sphinx-9461,sphinx-doc__sphinx-9698"
```

### Batch D1 — scikit-learn part 1 (8 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_2 \
  --parallel 2 \
  --filter "scikit-learn__scikit-learn-10427,scikit-learn__scikit-learn-10803,scikit-learn__scikit-learn-11206,scikit-learn__scikit-learn-11596,scikit-learn__scikit-learn-12704,scikit-learn__scikit-learn-13013,scikit-learn__scikit-learn-13283,scikit-learn__scikit-learn-13496"
```

### Batch D2 — scikit-learn part 2 (7 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_2 \
  --parallel 2 \
  --filter "scikit-learn__scikit-learn-13864,scikit-learn__scikit-learn-14125,scikit-learn__scikit-learn-14710,scikit-learn__scikit-learn-15094,scikit-learn__scikit-learn-24677,scikit-learn__scikit-learn-25694,scikit-learn__scikit-learn-3840"
```

### Batch D3 — matplotlib (12 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_2 \
  --parallel 2 \
  --filter "matplotlib__matplotlib-13859,matplotlib__matplotlib-19763,matplotlib__matplotlib-21042,matplotlib__matplotlib-22767,matplotlib__matplotlib-23088,matplotlib__matplotlib-23476,matplotlib__matplotlib-24177,matplotlib__matplotlib-24637,matplotlib__matplotlib-25126,matplotlib__matplotlib-25442,matplotlib__matplotlib-25772,matplotlib__matplotlib-26160"
```

### Batch D4 — xarray + astropy (11 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_2 \
  --parallel 2 \
  --filter "pydata__xarray-2905,pydata__xarray-3520,pydata__xarray-4075,pydata__xarray-4629,pydata__xarray-4911,pydata__xarray-5455,pydata__xarray-6601,pydata__xarray-7003,astropy__astropy-12962,astropy__astropy-13842,astropy__astropy-6938"
```

### Batch D5 — sympy + seaborn (12 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_2 \
  --parallel 2 \
  --filter "sympy__sympy-11232,sympy__sympy-13259,sympy__sympy-14180,sympy__sympy-15976,sympy__sympy-17318,sympy__sympy-19016,sympy__sympy-21596,mwaskom__seaborn-2389,mwaskom__seaborn-2813,mwaskom__seaborn-2946,mwaskom__seaborn-3069,mwaskom__seaborn-3202"
```

### Seed 2 analysis

```bash
python -m swebench analyze summary \
  --results-dir runs/swebench/full_run_seed_2 \
  --out runs/swebench/full_run_seed_2/summary.csv
```

---

## Seed 3 — `runs/swebench/full_run_seed_3/`

### Batch V1 — Django part 1 (13 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_3 \
  --parallel 2 \
  --filter "django__django-11790,django__django-11815,django__django-11848,django__django-11880,django__django-11885,django__django-11951,django__django-11964,django__django-11999,django__django-12039,django__django-12050,django__django-12143,django__django-12155,django__django-12193"
```

### Batch V2 — Django part 2 (12 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_3 \
  --parallel 2 \
  --filter "django__django-12209,django__django-12262,django__django-12273,django__django-12276,django__django-12304,django__django-12308,django__django-12325,django__django-12406,django__django-12708,django__django-12713,django__django-12774,django__django-9296"
```

### Batch V3 — Sphinx part 1 (13 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_3 \
  --parallel 2 \
  --filter "sphinx-doc__sphinx-10323,sphinx-doc__sphinx-10435,sphinx-doc__sphinx-10466,sphinx-doc__sphinx-10673,sphinx-doc__sphinx-11510,sphinx-doc__sphinx-7590,sphinx-doc__sphinx-7748,sphinx-doc__sphinx-7757,sphinx-doc__sphinx-7985,sphinx-doc__sphinx-8035,sphinx-doc__sphinx-8056,sphinx-doc__sphinx-8265,sphinx-doc__sphinx-8269"
```

### Batch V4 — Sphinx part 2 (12 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_3 \
  --parallel 2 \
  --filter "sphinx-doc__sphinx-8475,sphinx-doc__sphinx-8548,sphinx-doc__sphinx-8551,sphinx-doc__sphinx-8638,sphinx-doc__sphinx-8721,sphinx-doc__sphinx-9229,sphinx-doc__sphinx-9230,sphinx-doc__sphinx-9281,sphinx-doc__sphinx-9320,sphinx-doc__sphinx-9367,sphinx-doc__sphinx-9461,sphinx-doc__sphinx-9698"
```

### Batch D1 — scikit-learn part 1 (8 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_3 \
  --parallel 2 \
  --filter "scikit-learn__scikit-learn-10427,scikit-learn__scikit-learn-10803,scikit-learn__scikit-learn-11206,scikit-learn__scikit-learn-11596,scikit-learn__scikit-learn-12704,scikit-learn__scikit-learn-13013,scikit-learn__scikit-learn-13283,scikit-learn__scikit-learn-13496"
```

### Batch D2 — scikit-learn part 2 (7 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_3 \
  --parallel 2 \
  --filter "scikit-learn__scikit-learn-13864,scikit-learn__scikit-learn-14125,scikit-learn__scikit-learn-14710,scikit-learn__scikit-learn-15094,scikit-learn__scikit-learn-24677,scikit-learn__scikit-learn-25694,scikit-learn__scikit-learn-3840"
```

### Batch D3 — matplotlib (12 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_3 \
  --parallel 2 \
  --filter "matplotlib__matplotlib-13859,matplotlib__matplotlib-19763,matplotlib__matplotlib-21042,matplotlib__matplotlib-22767,matplotlib__matplotlib-23088,matplotlib__matplotlib-23476,matplotlib__matplotlib-24177,matplotlib__matplotlib-24637,matplotlib__matplotlib-25126,matplotlib__matplotlib-25442,matplotlib__matplotlib-25772,matplotlib__matplotlib-26160"
```

### Batch D4 — xarray + astropy (11 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_3 \
  --parallel 2 \
  --filter "pydata__xarray-2905,pydata__xarray-3520,pydata__xarray-4075,pydata__xarray-4629,pydata__xarray-4911,pydata__xarray-5455,pydata__xarray-6601,pydata__xarray-7003,astropy__astropy-12962,astropy__astropy-13842,astropy__astropy-6938"
```

### Batch D5 — sympy + seaborn (12 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_seed_3 \
  --parallel 2 \
  --filter "sympy__sympy-11232,sympy__sympy-13259,sympy__sympy-14180,sympy__sympy-15976,sympy__sympy-17318,sympy__sympy-19016,sympy__sympy-21596,mwaskom__seaborn-2389,mwaskom__seaborn-2813,mwaskom__seaborn-2946,mwaskom__seaborn-3069,mwaskom__seaborn-3202"
```

### Seed 3 analysis

```bash
python -m swebench analyze summary \
  --results-dir runs/swebench/full_run_seed_3 \
  --out runs/swebench/full_run_seed_3/summary.csv
```

---

## Cross-seed analysis

Once all three seeds are complete, compare per-instance pass rates across seeds to estimate variance:

```bash
python -m swebench analyze summary --results-dir runs/swebench/full_run_seed_1 --out runs/swebench/full_run_seed_1/summary.csv
python -m swebench analyze summary --results-dir runs/swebench/full_run_seed_2 --out runs/swebench/full_run_seed_2/summary.csv
python -m swebench analyze summary --results-dir runs/swebench/full_run_seed_3 --out runs/swebench/full_run_seed_3/summary.csv
```

Then aggregate the three CSVs to get mean pass rate ± stderr per arm.
