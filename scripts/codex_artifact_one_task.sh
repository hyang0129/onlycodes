#!/usr/bin/env bash
# Run ONE artifact task through a DEDICATED mitm proxy.
#
# Usage: scripts/codex_artifact_one_task.sh <instance_id> [output_dir]
#
# Spins up a fresh mitmdump on a free port, sets HTTPS_PROXY for the
# subprocess, runs the harness for one task (all 3 arms), captures
# per-call traffic into /tmp/codex_capture_per_task/<task>/, kills mitm.
#
# Safe to run in parallel — each invocation has its own mitm and
# capture dir, so no shared-state contention from the proxy side.

set -u

TASK=${1:?"usage: $0 <instance_id> [output_dir]"}
OUT=${2:-runs/artifact/full_run_seed_1_codex}

cd "$(dirname "$0")/.."
source .venv/bin/activate

# Get a free TCP port
PORT=$(python -c "import socket; s=socket.socket(); s.bind(('',0)); print(s.getsockname()[1]); s.close()")

CAPDIR=/tmp/codex_capture_per_task/$TASK
mkdir -p "$CAPDIR"
MITM_LOG=$(mktemp -t mitm_${TASK}_XXX.log)

# Spin up dedicated mitm
ONLYCODES_CAPTURE_DIR="$CAPDIR" \
  .venv/bin/mitmdump --listen-port "$PORT" --set confdir=/tmp/mitmproxy-conf \
  -s scripts/codex_capture_per_task.py \
  > "$MITM_LOG" 2>&1 &
MITM_PID=$!
trap "kill $MITM_PID 2>/dev/null; rm -f $MITM_LOG" EXIT

# Wait for mitm to be ready
for i in 1 2 3 4 5; do
  if curl -s -o /dev/null --connect-timeout 1 -x http://127.0.0.1:$PORT http://example.com/ 2>/dev/null; then
    break
  fi
  sleep 1
done

echo "[$(date +%H:%M:%S)] [$TASK] mitm pid=$MITM_PID port=$PORT capture=$CAPDIR"

# Run the harness
HTTPS_PROXY=http://127.0.0.1:$PORT \
HTTP_PROXY=http://127.0.0.1:$PORT \
SSL_CERT_FILE=/tmp/mitmproxy-conf/mitmproxy-ca-cert.pem \
NODE_EXTRA_CA_CERTS=/tmp/mitmproxy-conf/mitmproxy-ca-cert.pem \
REQUESTS_CA_BUNDLE=/tmp/mitmproxy-conf/mitmproxy-ca-cert.pem \
SWEBENCH_CACHE_ROOT=/tmp/swebench-cache \
  timeout 600 python -m swebench artifact run \
    --output-dir "$OUT" \
    --resume \
    --arms all \
    --agent-surface codex_cli \
    --codex-model gpt-5.5 \
    --filter "$TASK"
RC=$?

# Brief summary
echo "[$(date +%H:%M:%S)] [$TASK] harness rc=$RC, capture: $(ls "$CAPDIR" 2>/dev/null | wc -l) files"
exit $RC
