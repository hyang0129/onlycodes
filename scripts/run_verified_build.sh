#!/usr/bin/env bash
# WS-A.2 (#308) hand-off: materialize the full SWE-bench Verified pool and build
# the frozen buildable set the spine (#299) and deconfound subset (#301) draw from.
#
# This is the LONG-RUNNING op (hours–days of cache builds, ~230 GB of disk for
# the full 500). Run it detached and monitor the tee'd log + disk. It is safe to
# re-run: `add` overwrites YAMLs idempotently and the validator's Gate-1 cache
# build skips already-cached instances.
#
# Produces:
#   problems/swe/swebench-verified/*.yaml   (500 materialized tasks)
#   sets/verified-buildable.txt             (built + collected-cleanly subset)
#   runs/validation/swebench-verified_<ts>/ (summary.md, results.json, logs/)
#
# set -u (NOT -e): one bad instance must not abort the whole pass — the validator
# keeps going on every failure and the report is the deliverable.
set -u

cd "$(dirname "$0")/.."
source .venv/bin/activate
export SWEBENCH_CACHE_ROOT="${SWEBENCH_CACHE_ROOT:-/tmp/swebench-cache}"

SPINE_IDS="${SPINE_IDS:-sets/verified-spine.txt}"
CONCURRENCY="${CONCURRENCY:-8}"
TIMEOUT="${TIMEOUT:-2400}"
LOG="${LOG:-/tmp/verified_build_$(date +%Y%m%dT%H%M%SZ).log}"

if [ ! -f "$SPINE_IDS" ]; then
  echo "ERROR: spine id-file not found: $SPINE_IDS (run scripts/list_verified_ids.py first)" >&2
  exit 1
fi
N_IDS=$(grep -vc '^\s*\(#\|$\)' "$SPINE_IDS")
echo "### [$(date -Iseconds)] Materializing $N_IDS Verified ids -> problems/swe/swebench-verified/"
echo "### cache root: $SWEBENCH_CACHE_ROOT | concurrency: $CONCURRENCY | log: $LOG"
df -h "$SWEBENCH_CACHE_ROOT" 2>/dev/null | tail -1

# 1. Materialize YAMLs (network-bound, fast relative to the cache build).
python -m swebench add --from-file "$SPINE_IDS" \
  --set swe/swebench-verified --concurrency "$CONCURRENCY" 2>&1 | tee -a "$LOG"

# 2. Retire the now-redundant verified-mini set: its 50 ids are a subset of the
#    500, and `swebench run` rglobs ALL of problems/swe/** then filters by id, so
#    a duplicate id would run the instance TWICE per arm/seed and corrupt the
#    spine denominator (#299). The validator below is set-scoped and unaffected,
#    but the spine is not — retire mini in a reviewed commit BEFORE running #299.
if [ -d problems/swe/swebench-verified-mini ]; then
  echo "" | tee -a "$LOG"
  echo "WARNING: problems/swe/swebench-verified-mini/ still present — its ids are a" | tee -a "$LOG"
  echo "         subset of the 500 and will DOUBLE-RUN in the spine. Retire it with:" | tee -a "$LOG"
  echo "             git rm -r problems/swe/swebench-verified-mini patches/*mini* 2>/dev/null" | tee -a "$LOG"
  echo "         (commit separately; the build below is set-scoped and proceeds safely)." | tee -a "$LOG"
fi

# 3. Build + validate the full pool; write the buildable subset to the committed
#    location the spine reads (run --filter @sets/verified-buildable.txt).
echo "" | tee -a "$LOG"
echo "### [$(date -Iseconds)] Validating (cache-build + collect) over the pool" | tee -a "$LOG"
python scripts/validate_verified_setup.py \
  --set swe/swebench-verified \
  --filter "@$SPINE_IDS" \
  --concurrency "$CONCURRENCY" \
  --timeout "$TIMEOUT" \
  --buildable-out sets/verified-buildable.txt 2>&1 | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "=== [$(date -Iseconds)] VERIFIED BUILD DONE ===" | tee -a "$LOG"
echo "Buildable set: sets/verified-buildable.txt" | tee -a "$LOG"
echo "Commit sets/verified-buildable.txt + the shortfall from the summary, then #299 can run." | tee -a "$LOG"
df -h "$SWEBENCH_CACHE_ROOT" 2>/dev/null | tail -1 | tee -a "$LOG"
