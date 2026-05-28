#!/usr/bin/env bash
# SWE-bench codex v2 — all 3 seeds × 100 instances × 3 arms.
#
# --parallel 6: 6 instances run concurrently, each running all 3 arms.
# Seeds run sequentially.
#
# Output: runs/swebench/full_run_seed_N_codex_v2/

set -u
cd "$(dirname "$0")/.."
source .venv/bin/activate
export SWEBENCH_CACHE_ROOT=/tmp/swebench-cache

SEEDS=(1 2 3)

for seed in "${SEEDS[@]}"; do
  OUT="runs/swebench/full_run_seed_${seed}_codex_v2"
  LOGDIR="$OUT/_driver_logs"
  mkdir -p "$LOGDIR"

  echo ""
  echo "########################################"
  echo "### [$(date -Iseconds)] SWEBENCH SEED $seed -> $OUT"
  echo "########################################"

  python -m swebench run \
    --output-dir "$OUT" \
    --parallel 6 \
    --use-cache \
    --resume \
    --arms all \
    --agent-surface codex_cli \
    --codex-model gpt-5.5 \
    < /dev/null 2>&1 | tee "$LOGDIR/full_sweep.log"

  echo "=== [$(date -Iseconds)] seed $seed done ==="
done

echo ""
echo "=== [$(date -Iseconds)] ALL SEEDS DONE ==="
