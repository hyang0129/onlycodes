# Batched SWE-bench Mini Run

100 problems split across two sets and 9 batches. All batches write to the same output dir so `analyze` sees a single cohesive run.

## Sets

| Set | Problems | Repos | Batches |
|---|---|---|---|
| swebench-verified-mini | 50 | Django (25), Sphinx (25) | V1–V4 |
| swebench-datasci-mini | 50 | scikit-learn (15), matplotlib (12), xarray (8), sympy (7), seaborn (5), astropy (3) | D1–D5 |

## How it works

- `--output-dir` is fixed across all batches — results accumulate under `runs/swebench/full_run_v1/`
- `--resume` (default on) skips any `(instance, arm, run)` triple that already has a result, so re-running a batch is safe
- Same-repo batches share the OverlayFS cache, so sequential same-repo batches are faster than cross-repo ones
- Arms: `baseline` (full tool suite) and `onlycode` (execute_code MCP only)

## Commands

```bash
cd /workspaces/hub_1/onlycodes
source .venv/bin/activate
```

---

## verified-mini batches

### Batch V1 — Django part 1 (13 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_v1 \
  --filter "django__django-11790,django__django-11815,django__django-11848,django__django-11880,django__django-11885,django__django-11951,django__django-11964,django__django-11999,django__django-12039,django__django-12050,django__django-12143,django__django-12155,django__django-12193"
```

### Batch V2 — Django part 2 (12 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_v1 \
  --filter "django__django-12209,django__django-12262,django__django-12273,django__django-12276,django__django-12304,django__django-12308,django__django-12325,django__django-12406,django__django-12708,django__django-12713,django__django-12774,django__django-9296"
```

### Batch V3 — Sphinx part 1 (13 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_v1 \
  --filter "sphinx-doc__sphinx-10323,sphinx-doc__sphinx-10435,sphinx-doc__sphinx-10466,sphinx-doc__sphinx-10673,sphinx-doc__sphinx-11510,sphinx-doc__sphinx-7590,sphinx-doc__sphinx-7748,sphinx-doc__sphinx-7757,sphinx-doc__sphinx-7985,sphinx-doc__sphinx-8035,sphinx-doc__sphinx-8056,sphinx-doc__sphinx-8265,sphinx-doc__sphinx-8269"
```

### Batch V4 — Sphinx part 2 (12 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_v1 \
  --filter "sphinx-doc__sphinx-8475,sphinx-doc__sphinx-8548,sphinx-doc__sphinx-8551,sphinx-doc__sphinx-8638,sphinx-doc__sphinx-8721,sphinx-doc__sphinx-9229,sphinx-doc__sphinx-9230,sphinx-doc__sphinx-9281,sphinx-doc__sphinx-9320,sphinx-doc__sphinx-9367,sphinx-doc__sphinx-9461,sphinx-doc__sphinx-9698"
```

---

## datasci-mini batches

### Batch D1 — scikit-learn part 1 (8 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_v1 \
  --filter "scikit-learn__scikit-learn-10427,scikit-learn__scikit-learn-10803,scikit-learn__scikit-learn-11206,scikit-learn__scikit-learn-11596,scikit-learn__scikit-learn-12704,scikit-learn__scikit-learn-13013,scikit-learn__scikit-learn-13283,scikit-learn__scikit-learn-13496"
```

### Batch D2 — scikit-learn part 2 (7 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_v1 \
  --filter "scikit-learn__scikit-learn-13864,scikit-learn__scikit-learn-14125,scikit-learn__scikit-learn-14710,scikit-learn__scikit-learn-15094,scikit-learn__scikit-learn-24677,scikit-learn__scikit-learn-25694,scikit-learn__scikit-learn-3840"
```

### Batch D3 — matplotlib (12 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_v1 \
  --filter "matplotlib__matplotlib-13859,matplotlib__matplotlib-19763,matplotlib__matplotlib-21042,matplotlib__matplotlib-22767,matplotlib__matplotlib-23088,matplotlib__matplotlib-23476,matplotlib__matplotlib-24177,matplotlib__matplotlib-24637,matplotlib__matplotlib-25126,matplotlib__matplotlib-25442,matplotlib__matplotlib-25772,matplotlib__matplotlib-26160"
```

### Batch D4 — xarray + astropy (11 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_v1 \
  --filter "pydata__xarray-2905,pydata__xarray-3520,pydata__xarray-4075,pydata__xarray-4629,pydata__xarray-4911,pydata__xarray-5455,pydata__xarray-6601,pydata__xarray-7003,astropy__astropy-12962,astropy__astropy-13842,astropy__astropy-6938"
```

### Batch D5 — sympy + seaborn (12 problems)

```bash
python -m swebench run \
  --output-dir runs/swebench/full_run_v1 \
  --filter "sympy__sympy-11232,sympy__sympy-13259,sympy__sympy-14180,sympy__sympy-15976,sympy__sympy-17318,sympy__sympy-19016,sympy__sympy-21596,mwaskom__seaborn-2389,mwaskom__seaborn-2813,mwaskom__seaborn-2946,mwaskom__seaborn-3069,mwaskom__seaborn-3202"
```

---

## Intermediate analysis

Run at any point — problems with no results yet won't appear:

```bash
python -m swebench analyze --results-dir runs/swebench/full_run_v1
```

## Final analysis

Same command once all 9 batches are done:

```bash
python -m swebench analyze \
  --results-dir runs/swebench/full_run_v1 \
  --out runs/swebench/full_run_v1/summary.csv
```
