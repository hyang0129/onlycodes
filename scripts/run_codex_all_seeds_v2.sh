#!/usr/bin/env bash
# Full codex re-run with per-API-call rollout capture (2026-05-27).
#
# Each arm invocation now preserves $CODEX_HOME/sessions/*/rollout-*.jsonl
# as <result_file>.rollout.jsonl, giving us per-call token_count events
# with last_token_usage (input/cached/output per call). Required for the
# first-call cache adjustment in paper §3.5.
#
# Output: runs/{artifact,swebench}/full_run_seed_N_codex_v2/
#         (existing _codex/ dirs untouched as backups)
#
# Schedule: artifact seeds 1-3, then swebench seeds 1-3 (sequential).
# Within each seed: PER-ARM parallel=6 sweeps (code_only, tool_rich,
# bash_only one at a time). Per-arm batching is verified safe at parallel=6;
# the previous --arms all approach hit an intermittent failure at scale
# (~33% pass) for tool_rich/bash_only even with apps=false.

set -u
cd "$(dirname "$0")/.."
source .venv/bin/activate
export SWEBENCH_CACHE_ROOT=/tmp/swebench-cache

SEEDS=(1 2 3)
# Unified parallel=6 across all arms (2026-05-27). Root cause of earlier
# tool_rich/bash_only INFRA cascades was codex's curated-plugin loader
# (github@openai-curated) racing when cwd was inside a git repo — NOT a
# parallelism issue. Fix landed in artifact_materialize.py: tool_rich/
# bash_only scratch dirs now live under /tmp/onlycodes_scratch (off-repo),
# which side-steps the plugin loader entirely. Verified 12/12 PASS at
# parallel=6 on the real output dir.
PARALLEL=6              # artifact: lightweight tasks
SWEBENCH_PARALLEL=4     # swebench: heavier (real repos + overlay mounts); 4 verified safe
ARMS=(code_only tool_rich bash_only)

# --- Artifact task IDs (gathered once) ---
ARTIFACT_TASKS=$(python -c "
import yaml
from pathlib import Path
for t in sorted(Path('problems/artifact').rglob('task.yaml')):
    print(yaml.safe_load(open(t))['instance_id'])
")
N_ART=$(echo "$ARTIFACT_TASKS" | wc -l)

# --- Per-(task, arm) wrapper for artifact ---
# (Earlier jitter sleep removed: it was a band-aid for the plugin-loader
# race that's now fixed at the source via off-repo scratch dirs.)
run_one_artifact_task_arm() {
  local task="$1"
  local arm="$2"
  local out="$3"
  local logdir="$4"
  local log="$logdir/${arm}__${task}.log"
  echo "[$(date +%H:%M:%S)] [START] $arm $task" >> "$logdir/_master.log"
  timeout 600 python -m swebench artifact run \
    --output-dir "$out" \
    --resume \
    --arms "$arm" \
    --agent-surface codex_cli \
    --codex-model gpt-5.5 \
    --filter "$task" \
    > "$log" 2>&1
  local rc=$?
  local pass fail
  pass=$(grep -c "PASS (wall=" "$log" 2>/dev/null)
  fail=$(grep -c "FAIL (wall=" "$log" 2>/dev/null)
  echo "[$(date +%H:%M:%S)] [DONE]  $arm $task rc=$rc PASS=$pass FAIL=$fail" >> "$logdir/_master.log"
}
export -f run_one_artifact_task_arm

# --- Run artifact seeds (per-arm sweeps) ---
for seed in "${SEEDS[@]}"; do
  OUT="runs/artifact/full_run_seed_${seed}_codex_v2"
  LOGDIR="$OUT/_driver_logs"
  mkdir -p "$LOGDIR"
  echo ""
  echo "########################################"
  echo "### [$(date -Iseconds)] ARTIFACT SEED $seed -> $OUT (parallel=$PARALLEL, per-arm)"
  echo "########################################"
  for arm in "${ARMS[@]}"; do
    echo "=== [$(date -Iseconds)] artifact seed $seed arm=$arm: $N_ART tasks (parallel=$PARALLEL) ===" | tee -a "$LOGDIR/_master.log"
    echo "$ARTIFACT_TASKS" | xargs -P "$PARALLEL" -I {} \
      bash -c 'run_one_artifact_task_arm "$1" "$2" "$3" "$4"' _ {} "$arm" "$OUT" "$LOGDIR"
    echo "=== [$(date -Iseconds)] artifact seed $seed arm=$arm DONE ===" | tee -a "$LOGDIR/_master.log"
  done
done

# --- Wait for any in-progress Claude swebench run to finish ---
echo ""
echo "=== [$(date -Iseconds)] checking for active Claude swebench runs before codex swebench portion ==="
while pgrep -af "python -m swebench run " | grep -v codex_cli | grep -q .; do
  active=$(pgrep -af "python -m swebench run " | grep -v codex_cli | head -1)
  echo "[$(date -Iseconds)] waiting on: $active"
  sleep 60
done
echo "=== [$(date -Iseconds)] no conflicting swebench runs — starting codex swebench portion ==="

# --- Run swebench seeds (per-arm sweeps; swebench supports --arms <arm>) ---
for seed in "${SEEDS[@]}"; do
  OUT="runs/swebench/full_run_seed_${seed}_codex_v2"
  LOGDIR="$OUT/_driver_logs"
  mkdir -p "$LOGDIR"
  echo ""
  echo "########################################"
  echo "### [$(date -Iseconds)] SWEBENCH SEED $seed -> $OUT (parallel=$SWEBENCH_PARALLEL, per-arm)"
  echo "########################################"
  # swebench arm names: baseline, onlycode, bash_only
  for arm in onlycode baseline bash_only; do
    echo "=== [$(date -Iseconds)] swebench seed $seed arm=$arm (parallel=$SWEBENCH_PARALLEL) ==="
    python -m swebench run \
      --output-dir "$OUT" \
      --parallel "$SWEBENCH_PARALLEL" \
      --use-cache \
      --resume \
      --arms "$arm" \
      --agent-surface codex_cli \
      --codex-model gpt-5.5 \
      < /dev/null 2>&1 | tee "$LOGDIR/full_sweep_${arm}.log"
  done
done

echo ""
echo "=== [$(date -Iseconds)] ALL SEEDS DONE ==="
