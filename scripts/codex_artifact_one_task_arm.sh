#!/usr/bin/env bash
# Run ONE artifact task × ONE arm through a DEDICATED mitm proxy.
#
# Usage: scripts/codex_artifact_one_task_arm.sh <instance_id> <arm> [output_dir]
# arm ∈ {code_only, tool_rich, bash_only, all}
#
# Sister script to codex_artifact_one_task.sh which always runs all 3 arms;
# this one lets you run just one arm, so we can do a bash_only-only sweep
# without re-running code_only that we already have.

set -u

TASK=${1:?"usage: $0 <instance_id> <arm> [output_dir]"}
ARM=${2:?"usage: $0 <instance_id> <arm> [output_dir]"}
OUT=${3:-runs/artifact/seed_1_codex_proxy}

cd "$(dirname "$0")/.."
source .venv/bin/activate

PORT=$(python -c "import socket; s=socket.socket(); s.bind(('',0)); print(s.getsockname()[1]); s.close()")

CAPDIR=/tmp/codex_capture_per_task/$TASK
mkdir -p "$CAPDIR"
MITM_LOG=$(mktemp -t mitm_${TASK}_${ARM}_XXX.log)

ONLYCODES_CAPTURE_DIR="$CAPDIR" \
  .venv/bin/mitmdump --listen-port "$PORT" --set confdir=/tmp/mitmproxy-conf \
  -s scripts/codex_capture_per_task.py \
  > "$MITM_LOG" 2>&1 &
MITM_PID=$!
trap "kill $MITM_PID 2>/dev/null; rm -f $MITM_LOG" EXIT

# Wait for mitm
for i in 1 2 3 4 5; do
  if curl -s -o /dev/null --connect-timeout 1 -x http://127.0.0.1:$PORT http://example.com/ 2>/dev/null; then
    break
  fi
  sleep 1
done

echo "[$(date +%H:%M:%S)] [$TASK/$ARM] mitm pid=$MITM_PID port=$PORT capture=$CAPDIR"

HTTPS_PROXY=http://127.0.0.1:$PORT \
HTTP_PROXY=http://127.0.0.1:$PORT \
SSL_CERT_FILE=/tmp/mitmproxy-conf/mitmproxy-ca-cert.pem \
NODE_EXTRA_CA_CERTS=/tmp/mitmproxy-conf/mitmproxy-ca-cert.pem \
REQUESTS_CA_BUNDLE=/tmp/mitmproxy-conf/mitmproxy-ca-cert.pem \
SWEBENCH_CACHE_ROOT=/tmp/swebench-cache \
  timeout 600 python -m swebench artifact run \
    --output-dir "$OUT" \
    --resume \
    --arms "$ARM" \
    --agent-surface codex_cli \
    --codex-model gpt-5.5 \
    --filter "$TASK"
RC=$?

echo "[$(date +%H:%M:%S)] [$TASK/$ARM] harness rc=$RC, capture: $(ls "$CAPDIR" 2>/dev/null | wc -l) files"
exit $RC
