#!/usr/bin/env bash
# WS-A modification-regime spine (#299): the buildable SWE-bench Verified subset
# × 3 arms (baseline/onlycode/bash_only) × 3 seeds × 2 native agents
# (Claude Code / sonnet-4-6, Codex CLI / gpt-5.5), on the existing harness.
#
# Depends on:
#   * #308 (WS-A.2) having produced sets/verified-buildable.txt + a warmed cache.
#   * #307 (WS-A.1) for N*: if the power analysis says a subset suffices, point
#     SPINE_IDS at the powered id-file instead of the full buildable list.
#
# Seeds are independent replications in separate output dirs (the established
# convention from run_all_seeds_claude.sh); the agent itself has no RNG seed,
# so "seed" captures model stochasticity. Arms run serially within an instance
# (shared overlay); --parallel parallelises across instances.
#
# set -u (NOT -e): a credential cliff or one bad instance must not abort the
# whole grid — --resume fills the gaps on a rerun.
set -u

cd "$(dirname "$0")/.."
source .venv/bin/activate
export SWEBENCH_CACHE_ROOT="${SWEBENCH_CACHE_ROOT:-/tmp/swebench-cache}"

SPINE_IDS="${SPINE_IDS:-sets/verified-buildable.txt}"
SEEDS=(${SEEDS:-1 2 3})
PARALLEL="${PARALLEL:-4}"          # swebench is heavy (real repos + overlay mounts)
AGENTS=(${AGENTS:-claude_code codex_cli})
CODEX_MODEL="${CODEX_MODEL:-gpt-5.5}"

if [ ! -f "$SPINE_IDS" ]; then
  echo "ERROR: spine id-file not found: $SPINE_IDS" >&2
  echo "       Run WS-A.2 (#308) first to materialize + cache-build SWE-bench" >&2
  echo "       Verified and emit the buildable id list, or set SPINE_IDS to a" >&2
  echo "       powered subset id-file from WS-A.1 (#307)." >&2
  exit 1
fi
N_IDS=$(grep -vc '^\s*\(#\|$\)' "$SPINE_IDS")
echo "Spine: $N_IDS instances × 3 arms × ${#SEEDS[@]} seeds × ${#AGENTS[@]} agents"

for agent in "${AGENTS[@]}"; do
  extra=()
  [ "$agent" = "codex_cli" ] && extra=(--codex-model "$CODEX_MODEL")
  for seed in "${SEEDS[@]}"; do
    OUT="runs/swebench/verified_spine_${agent}_seed_${seed}"
    mkdir -p "$OUT/_driver_logs"
    echo ""
    echo "### [$(date -Iseconds)] agent=$agent seed=$seed -> $OUT"
    python -m swebench run \
      --agent-surface "$agent" \
      "${extra[@]}" \
      --filter "@$SPINE_IDS" \
      --arms all \
      --output-dir "$OUT" \
      --parallel "$PARALLEL" \
      --use-cache \
      --resume \
      < /dev/null 2>&1 | tee "$OUT/_driver_logs/run.log"
    python -m swebench analyze summary --results-dir "$OUT" --out "$OUT/summary.csv" \
      2>&1 | tee "$OUT/_driver_logs/summary.log"
  done
done

echo ""
echo "### [$(date -Iseconds)] significance report (per agent)"
for agent in "${AGENTS[@]}"; do
  dirs=()
  for seed in "${SEEDS[@]}"; do dirs+=("runs/swebench/verified_spine_${agent}_seed_${seed}"); done
  python scripts/spine_significance.py \
    --agent "$agent" \
    --runs "${dirs[@]}" \
    --filter "@$SPINE_IDS" \
    --out-prefix "runs/swebench/_analysis/spine/${agent}" \
    2>&1 | tee "runs/swebench/_analysis/spine/${agent}.log"
done

echo ""
echo "=== [$(date -Iseconds)] SPINE DONE ==="
