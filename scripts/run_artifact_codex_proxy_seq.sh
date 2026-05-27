#!/usr/bin/env bash
# Single-chunk sequential codex artifact run through the mitm proxy.
# Parallel=1 because attempts at parallel=2 and parallel=4 caused
# `tool_rich` / `bash_only` codex invocations to fail instantly with
# "Error: No such file or directory (os error 2)" — the proxy can't
# stably handle multiple concurrent codex sessions.

set -u
cd "$(dirname "$0")/.."
source .venv/bin/activate

OUT=runs/artifact/full_run_seed_1_codex
LOGDIR="$OUT/_driver_logs"
mkdir -p "$LOGDIR"

# Proxy env inherited by the codex subprocess
export HTTPS_PROXY=http://127.0.0.1:8888
export HTTP_PROXY=http://127.0.0.1:8888
export SSL_CERT_FILE=/tmp/mitmproxy-conf/mitmproxy-ca-cert.pem
export NODE_EXTRA_CA_CERTS=/tmp/mitmproxy-conf/mitmproxy-ca-cert.pem
export REQUESTS_CA_BUNDLE=/tmp/mitmproxy-conf/mitmproxy-ca-cert.pem

LOG="$LOGDIR/sequential_proxy.log"
echo "=== [$(date -Iseconds)] START sequential run ===" | tee -a "$LOG"
python -m swebench artifact run \
  --output-dir "$OUT" \
  --resume \
  --arms all \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  2>&1 | tee -a "$LOG"
echo "=== [$(date -Iseconds)] END sequential run ===" | tee -a "$LOG"
