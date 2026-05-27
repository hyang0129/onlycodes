#!/usr/bin/env bash
# Launches the codex artifact run at effective parallel=2 by chunking tasks.
# Both chunks run concurrently, all routed through the mitm proxy on :8888
# so per-API-call usage is captured into /tmp/codex_capture/.
#
# NOTE: parallel=4 was attempted first (2026-05-26 22:02) and failed —
# concurrent codex startups raced on plugin/helper-binary loading and the
# tool_rich + bash_only arms exited instantly with "Error: No such file or
# directory" (codex_home under /tmp + apps=true plugin race). Sequential
# runs all 3 arms PASS through the proxy; parallel=2 is the conservative
# stable level.
#
# Requires:
#   - mitmproxy running on 127.0.0.1:8888 with /tmp/codex_capture/capture.py addon
#   - /tmp/mitmproxy-conf/mitmproxy-ca-cert.pem trusted by codex (via SSL_CERT_FILE)
#
# Resumes automatically (per-task per-arm) on re-run.

set -u
cd "$(dirname "$0")/.."
source .venv/bin/activate

OUT=runs/artifact/full_run_seed_1_codex
LOGDIR="$OUT/_driver_logs"
mkdir -p "$LOGDIR"

# Proxy env — inherited by each codex subprocess via os.environ.copy()
export HTTPS_PROXY=http://127.0.0.1:8888
export HTTP_PROXY=http://127.0.0.1:8888
export SSL_CERT_FILE=/tmp/mitmproxy-conf/mitmproxy-ca-cert.pem
export NODE_EXTRA_CA_CERTS=/tmp/mitmproxy-conf/mitmproxy-ca-cert.pem
export REQUESTS_CA_BUNDLE=/tmp/mitmproxy-conf/mitmproxy-ca-cert.pem

# Gather all task instance_ids from problems/artifact/<category>/<slug>/task.yaml
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
N_TOTAL=$(echo "$INSTANCES" | tr ',' '\n' | wc -l)
echo "Total tasks: $N_TOTAL"

# Split into 4 chunks
python <<PYEOF > /tmp/artifact_chunks.txt
ids = "$INSTANCES".split(",")
n = 2
for i in range(n):
    chunk = ids[i::n]  # round-robin assignment (balances category clusters)
    print(",".join(chunk))
PYEOF

run_chunk() {
  local idx=$1
  local filter=$2
  local log="$LOGDIR/chunk${idx}_proxy.log"
  echo "=== [$(date -Iseconds)] START chunk $idx ($(echo $filter | tr ',' '\n' | wc -l) tasks) ==="
  python -m swebench artifact run \
    --output-dir "$OUT" \
    --resume \
    --arms all \
    --agent-surface codex_cli \
    --codex-model gpt-5.5 \
    --filter "$filter" \
    > "$log" 2>&1
  local rc=$?
  echo "=== [$(date -Iseconds)] END chunk $idx (rc=$rc) ==="
}

# Launch 4 chunks in parallel
idx=1
while IFS= read -r filter; do
  run_chunk $idx "$filter" &
  idx=$((idx + 1))
done < /tmp/artifact_chunks.txt

wait
echo "=== [$(date -Iseconds)] ALL CHUNKS DONE ==="
