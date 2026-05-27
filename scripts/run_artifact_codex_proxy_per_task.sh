#!/usr/bin/env bash
# Per-task-subprocess codex artifact runner through the mitm proxy.
#
# Each task gets its own fresh `python -m swebench artifact run` invocation,
# avoiding the long-running-harness-process bug observed 2026-05-26:
# in-process task loops cause `tool_rich`/`bash_only` codex invocations to
# fail with "Error: No such file or directory (os error 2)" after the first
# task. We proved back-to-back separate Python processes work cleanly,
# so this driver runs each task in its own process.
#
# Parallel=1 (sequential tasks). ETA: ~30-45 min/seed (93 tasks × ~3 arms
# × ~20s/arm = ~1.5h actual codex work + ~5s/task python overhead).

set -u
cd "$(dirname "$0")/.."
source .venv/bin/activate

OUT=runs/artifact/full_run_seed_1_codex
LOGDIR="$OUT/_driver_logs"
mkdir -p "$LOGDIR"
MASTER_LOG="$LOGDIR/per_task_proxy.log"

# Proxy env — inherited by each subprocess
export HTTPS_PROXY=http://127.0.0.1:8888
export HTTP_PROXY=http://127.0.0.1:8888
export SSL_CERT_FILE=/tmp/mitmproxy-conf/mitmproxy-ca-cert.pem
export NODE_EXTRA_CA_CERTS=/tmp/mitmproxy-conf/mitmproxy-ca-cert.pem
export REQUESTS_CA_BUNDLE=/tmp/mitmproxy-conf/mitmproxy-ca-cert.pem
export SWEBENCH_CACHE_ROOT=/tmp/swebench-cache

# Collect all task instance_ids
INSTANCES=$(python -c "
import yaml
from pathlib import Path
ids = []
for t in sorted(Path('problems/artifact').rglob('task.yaml')):
    with open(t) as f:
        d = yaml.safe_load(f)
    ids.append(d['instance_id'])
print(','.join(ids))
")
N=$(echo "$INSTANCES" | tr ',' '\n' | wc -l)
echo "=== [$(date -Iseconds)] START per-task driver: $N tasks ===" | tee -a "$MASTER_LOG"

done_count=0
for task in $(echo "$INSTANCES" | tr ',' ' '); do
  done_count=$((done_count + 1))
  TASK_LOG="$LOGDIR/per_task_${task}.log"
  echo "=== [$(date +%H:%M:%S)] [$done_count/$N] $task ===" | tee -a "$MASTER_LOG"
  python -m swebench artifact run \
    --output-dir "$OUT" \
    --resume \
    --arms all \
    --agent-surface codex_cli \
    --codex-model gpt-5.5 \
    --filter "$task" \
    > "$TASK_LOG" 2>&1
  rc=$?
  # Brief one-line summary to master log
  passes=$(grep -c "PASS (wall=" "$TASK_LOG")
  fails=$(grep -c "FAIL (wall=" "$TASK_LOG")
  echo "    rc=$rc  PASS=$passes FAIL=$fails" | tee -a "$MASTER_LOG"
done

echo "=== [$(date -Iseconds)] DONE ===" | tee -a "$MASTER_LOG"
