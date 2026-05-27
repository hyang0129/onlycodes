#!/usr/bin/env bash
# All 3 seeds × 100 SWE-bench instances × 3 arms (baseline, onlycode, bash_only)
# on Claude Code, --parallel 4, --use-cache, --resume.
#
# Seeds run sequentially (one at a time). Within a seed, the 100 instances are
# split into 9 batches matching the original seed_1 sweep, so a credential
# cliff in batch D5 doesn't trash batches V1–D4 (set -u not -e).
#
# Resume semantics: a triple is "complete" iff its .jsonl + _test.txt both
# exist and the test file's last line is PASS/FAIL/env_fail. The recent
# cleanup of seed_2's 4 interrupted JSONLs and seed_1/3's missing-JSONL slots
# means --resume will fill exactly the gaps we identified.
set -u  # NOT -e: continue to the next batch / seed even if one fails.

cd "$(dirname "$0")/.."
source .venv/bin/activate
export SWEBENCH_CACHE_ROOT=/tmp/swebench-cache

SEEDS=(1 2 3)

# Batch definitions (same V1–V4 + D1–D5 partition as scripts/run_seed1_all_batches.sh).
# Each line: BATCH_NAME|comma-separated filter list.
read -r -d '' BATCHES <<'EOF' || true
V1|django__django-11790,django__django-11815,django__django-11848,django__django-11880,django__django-11885,django__django-11951,django__django-11964,django__django-11999,django__django-12039,django__django-12050,django__django-12143,django__django-12155,django__django-12193
V2|django__django-12209,django__django-12262,django__django-12273,django__django-12276,django__django-12304,django__django-12308,django__django-12325,django__django-12406,django__django-12708,django__django-12713,django__django-12774,django__django-9296
V3|sphinx-doc__sphinx-10323,sphinx-doc__sphinx-10435,sphinx-doc__sphinx-10466,sphinx-doc__sphinx-10673,sphinx-doc__sphinx-11510,sphinx-doc__sphinx-7590,sphinx-doc__sphinx-7748,sphinx-doc__sphinx-7757,sphinx-doc__sphinx-7985,sphinx-doc__sphinx-8035,sphinx-doc__sphinx-8056,sphinx-doc__sphinx-8265,sphinx-doc__sphinx-8269
V4|sphinx-doc__sphinx-8475,sphinx-doc__sphinx-8548,sphinx-doc__sphinx-8551,sphinx-doc__sphinx-8638,sphinx-doc__sphinx-8721,sphinx-doc__sphinx-9229,sphinx-doc__sphinx-9230,sphinx-doc__sphinx-9281,sphinx-doc__sphinx-9320,sphinx-doc__sphinx-9367,sphinx-doc__sphinx-9461,sphinx-doc__sphinx-9698
D1|scikit-learn__scikit-learn-10427,scikit-learn__scikit-learn-10803,scikit-learn__scikit-learn-11206,scikit-learn__scikit-learn-11596,scikit-learn__scikit-learn-12704,scikit-learn__scikit-learn-13013,scikit-learn__scikit-learn-13283,scikit-learn__scikit-learn-13496
D2|scikit-learn__scikit-learn-13864,scikit-learn__scikit-learn-14125,scikit-learn__scikit-learn-14710,scikit-learn__scikit-learn-15094,scikit-learn__scikit-learn-24677,scikit-learn__scikit-learn-25694,scikit-learn__scikit-learn-3840
D3|matplotlib__matplotlib-13859,matplotlib__matplotlib-19763,matplotlib__matplotlib-21042,matplotlib__matplotlib-22767,matplotlib__matplotlib-23088,matplotlib__matplotlib-23476,matplotlib__matplotlib-24177,matplotlib__matplotlib-24637,matplotlib__matplotlib-25126,matplotlib__matplotlib-25442,matplotlib__matplotlib-25772,matplotlib__matplotlib-26160
D4|pydata__xarray-2905,pydata__xarray-3520,pydata__xarray-4075,pydata__xarray-4629,pydata__xarray-4911,pydata__xarray-5455,pydata__xarray-6601,pydata__xarray-7003,astropy__astropy-12962,astropy__astropy-13842,astropy__astropy-6938
D5|sympy__sympy-11232,sympy__sympy-13259,sympy__sympy-14180,sympy__sympy-15976,sympy__sympy-17318,sympy__sympy-19016,sympy__sympy-21596,mwaskom__seaborn-2389,mwaskom__seaborn-2813,mwaskom__seaborn-2946,mwaskom__seaborn-3069,mwaskom__seaborn-3202
EOF

run_batch() {
  local out="$1" name="$2" filter="$3"
  local logdir="$out/_driver_logs"
  local log="$logdir/${name}.log"
  mkdir -p "$logdir"
  echo "=== [$(date -Iseconds)] START $out / $name ==="
  # < /dev/null: prevent the python subprocess (or its Claude child) from
  # reading the outer `while read` loop's here-string, which would silently
  # exit the loop after this batch.
  python -m swebench run \
    --output-dir "$out" \
    --parallel 4 \
    --use-cache \
    --resume \
    --filter "$filter" \
    < /dev/null 2>&1 | tee "$log"
  local rc=${PIPESTATUS[0]}
  echo "=== [$(date -Iseconds)] END   $out / $name (rc=$rc) ==="
  return $rc
}

for seed in "${SEEDS[@]}"; do
  OUT="runs/swebench/full_run_seed_${seed}"
  echo ""
  echo "########################################"
  echo "### [$(date -Iseconds)] SEED $seed -> $OUT"
  echo "########################################"

  while IFS='|' read -r batch_name filter; do
    [ -z "$batch_name" ] && continue
    run_batch "$OUT" "$batch_name" "$filter"
  done <<< "$BATCHES"

  echo "=== [$(date -Iseconds)] SEED $seed regenerating summary ==="
  python -m swebench analyze summary \
    --results-dir "$OUT" \
    --out "$OUT/summary.csv" \
    2>&1 | tee "$OUT/_driver_logs/summary.log"
done

echo ""
echo "=== [$(date -Iseconds)] ALL SEEDS DONE ==="
