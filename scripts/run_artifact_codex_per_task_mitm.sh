#!/usr/bin/env bash
# Run all artifact tasks with per-codex (per-task) mitm at parallel=4.
#
# Each task gets its own dedicated mitm proxy on a free port + its own
# capture dir under /tmp/codex_capture_per_task/<task>/. Eliminates the
# shared-mitm contention that broke earlier parallel-2/parallel-4 attempts.
#
# Verified 2026-05-26: 4 concurrent tasks × 3 arms = 12/12 PASS.

set -u
cd "$(dirname "$0")/.."

OUT=${1:-runs/artifact/seed_1_codex_proxy}
PARALLEL=${2:-4}
LOGDIR="$OUT/_driver_logs"
mkdir -p "$LOGDIR"
MASTER_LOG="$LOGDIR/per_task_mitm_master.log"

# Gather task list
TASKS=$(.venv/bin/python -c "
import yaml
from pathlib import Path
for t in sorted(Path('problems/artifact').rglob('task.yaml')):
    print(yaml.safe_load(open(t))['instance_id'])
")
N=$(echo "$TASKS" | wc -l)
echo "=== [$(date -Iseconds)] START parallel=$PARALLEL per-task mitm driver: $N tasks → $OUT ===" | tee -a "$MASTER_LOG"

echo "$TASKS" | xargs -P "$PARALLEL" -I {} \
  bash -c '
    task=$1
    out=$2
    log=$3/per_task_${task}.log
    echo "[$(date +%H:%M:%S)] [START] $task" >> $3/per_task_mitm_master.log
    scripts/codex_artifact_one_task.sh "$task" "$out" > "$log" 2>&1
    rc=$?
    pass=$(grep -c "PASS (wall=" "$log")
    fail=$(grep -c "FAIL (wall=" "$log")
    echo "[$(date +%H:%M:%S)] [DONE]  $task rc=$rc PASS=$pass FAIL=$fail" >> $3/per_task_mitm_master.log
  ' _ {} "$OUT" "$LOGDIR"

echo "=== [$(date -Iseconds)] ALL DONE ===" | tee -a "$MASTER_LOG"
