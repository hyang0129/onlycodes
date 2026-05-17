#!/usr/bin/env bash
# Seed 1 — all 9 batches, all 3 arms, --parallel 4 --use-cache.
# Sequential batches; logs go to runs/swebench/full_run_seed_1/_driver_logs/.
set -u  # NOT -e: we want to continue to the next batch even if one fails.

cd "$(dirname "$0")/.."
source .venv/bin/activate
export SWEBENCH_CACHE_ROOT=/tmp/swebench-cache

OUT=runs/swebench/full_run_seed_1
LOGDIR="$OUT/_driver_logs"
mkdir -p "$LOGDIR"

run_batch() {
  local name="$1"
  local filter="$2"
  local log="$LOGDIR/${name}.log"
  echo "=== [$(date -Iseconds)] START $name ==="
  python -m swebench run \
    --output-dir "$OUT" \
    --parallel 4 \
    --use-cache \
    --filter "$filter" \
    2>&1 | tee "$log"
  local rc=${PIPESTATUS[0]}
  echo "=== [$(date -Iseconds)] END $name (rc=$rc) ==="
  return $rc
}

run_batch V1 "django__django-11790,django__django-11815,django__django-11848,django__django-11880,django__django-11885,django__django-11951,django__django-11964,django__django-11999,django__django-12039,django__django-12050,django__django-12143,django__django-12155,django__django-12193"
run_batch V2 "django__django-12209,django__django-12262,django__django-12273,django__django-12276,django__django-12304,django__django-12308,django__django-12325,django__django-12406,django__django-12708,django__django-12713,django__django-12774,django__django-9296"
run_batch V3 "sphinx-doc__sphinx-10323,sphinx-doc__sphinx-10435,sphinx-doc__sphinx-10466,sphinx-doc__sphinx-10673,sphinx-doc__sphinx-11510,sphinx-doc__sphinx-7590,sphinx-doc__sphinx-7748,sphinx-doc__sphinx-7757,sphinx-doc__sphinx-7985,sphinx-doc__sphinx-8035,sphinx-doc__sphinx-8056,sphinx-doc__sphinx-8265,sphinx-doc__sphinx-8269"
run_batch V4 "sphinx-doc__sphinx-8475,sphinx-doc__sphinx-8548,sphinx-doc__sphinx-8551,sphinx-doc__sphinx-8638,sphinx-doc__sphinx-8721,sphinx-doc__sphinx-9229,sphinx-doc__sphinx-9230,sphinx-doc__sphinx-9281,sphinx-doc__sphinx-9320,sphinx-doc__sphinx-9367,sphinx-doc__sphinx-9461,sphinx-doc__sphinx-9698"
run_batch D1 "scikit-learn__scikit-learn-10427,scikit-learn__scikit-learn-10803,scikit-learn__scikit-learn-11206,scikit-learn__scikit-learn-11596,scikit-learn__scikit-learn-12704,scikit-learn__scikit-learn-13013,scikit-learn__scikit-learn-13283,scikit-learn__scikit-learn-13496"
run_batch D2 "scikit-learn__scikit-learn-13864,scikit-learn__scikit-learn-14125,scikit-learn__scikit-learn-14710,scikit-learn__scikit-learn-15094,scikit-learn__scikit-learn-24677,scikit-learn__scikit-learn-25694,scikit-learn__scikit-learn-3840"
run_batch D3 "matplotlib__matplotlib-13859,matplotlib__matplotlib-19763,matplotlib__matplotlib-21042,matplotlib__matplotlib-22767,matplotlib__matplotlib-23088,matplotlib__matplotlib-23476,matplotlib__matplotlib-24177,matplotlib__matplotlib-24637,matplotlib__matplotlib-25126,matplotlib__matplotlib-25442,matplotlib__matplotlib-25772,matplotlib__matplotlib-26160"
run_batch D4 "pydata__xarray-2905,pydata__xarray-3520,pydata__xarray-4075,pydata__xarray-4629,pydata__xarray-4911,pydata__xarray-5455,pydata__xarray-6601,pydata__xarray-7003,astropy__astropy-12962,astropy__astropy-13842,astropy__astropy-6938"
run_batch D5 "sympy__sympy-11232,sympy__sympy-13259,sympy__sympy-14180,sympy__sympy-15976,sympy__sympy-17318,sympy__sympy-19016,sympy__sympy-21596,mwaskom__seaborn-2389,mwaskom__seaborn-2813,mwaskom__seaborn-2946,mwaskom__seaborn-3069,mwaskom__seaborn-3202"

echo "=== [$(date -Iseconds)] ALL BATCHES DONE ==="
python -m swebench analyze summary \
  --results-dir "$OUT" \
  --out "$OUT/summary.csv" 2>&1 | tee "$LOGDIR/summary.log"
