#!/usr/bin/env bash
# Serial (parallel=1) bash_only-only codex artifact run through per-task mitm.
#
# Strategy: chatgpt rate-limits codex sessions with plugin loader (apps=true),
# which both tool_rich and bash_only have. parallel=4 and parallel=2 both
# blew up because they exceed chatgpt's per-IP request rate. Serial gives
# each task uninterrupted access to chatgpt and adds breathing room.
#
# Estimated ~30-50s per bash_only invocation × 93 tasks ≈ 60-80 min.

set -u
cd "$(dirname "$0")/.."

OUT=${1:-runs/artifact/seed_1_codex_proxy}
LOGDIR="$OUT/_driver_logs"
mkdir -p "$LOGDIR"
MASTER_LOG="$LOGDIR/serial_bash_only_master.log"

TASKS=$(.venv/bin/python -c "
import yaml
from pathlib import Path
for t in sorted(Path('problems/artifact').rglob('task.yaml')):
    print(yaml.safe_load(open(t))['instance_id'])
")
N=$(echo "$TASKS" | wc -l)
echo "=== [$(date -Iseconds)] START serial bash_only driver: $N tasks → $OUT ===" | tee -a "$MASTER_LOG"

done_count=0
pass_count=0
fail_count=0
for task in $TASKS; do
  done_count=$((done_count + 1))
  TASK_LOG="$LOGDIR/serial_bash_only_${task}.log"
  echo "[$(date +%H:%M:%S)] [$done_count/$N] $task" | tee -a "$MASTER_LOG"
  scripts/codex_artifact_one_task_arm.sh "$task" bash_only "$OUT" > "$TASK_LOG" 2>&1
  rc=$?
  # Per-task summary
  passes=$(grep -c "PASS (wall=" "$TASK_LOG" 2>/dev/null)
  fails=$(grep -c "FAIL (wall=" "$TASK_LOG" 2>/dev/null)
  pass_count=$((pass_count + passes))
  fail_count=$((fail_count + fails))
  echo "    rc=$rc  PASS=$passes FAIL=$fails  running totals: $pass_count P / $fail_count F" | tee -a "$MASTER_LOG"
done

echo "=== [$(date -Iseconds)] DONE: $pass_count PASS / $fail_count FAIL across $N tasks ===" | tee -a "$MASTER_LOG"
