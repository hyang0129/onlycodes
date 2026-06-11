#!/bin/bash
# Auto-resume watchdog for the Tier 0 gold-496 run (#308).
# The docker daemon restarts ~every 12h (socket recreated root:root), which
# starves the run of socket access. This keeps the socket chmod'd and relaunches
# the run (resumable) if it dies, until all buildable instances are terminal.
set -u
cd /workspaces/hub_1/onlycodes
set -a; . ./.env 2>/dev/null; set +a
export ONLYCODES_MIN_FREE_GB=100
PAR=${T0_PARALLEL:-1}          # instances graded concurrently (keep small on shared hosts)
LOG=/tmp/t0_gold_496.log
RESULTS=runs/validation/agent-grade-t0/results_gold.json
TARGET=$(grep -vcE '^#|^\s*$' sets/verified-buildable.txt)

done_count() {
  # Count ALL processed instances (terminal + error), not just terminal: a
  # deterministic error (e.g. ContainerLeakError) never becomes terminal, so
  # counting terminal-only would loop forever re-running it. A daemon restart
  # instead KILLS the run mid-pass (rows < target -> relaunch continues); a clean
  # full pass reaches `target` rows and we stop, leaving any persistent errors for
  # offline triage.
  python3 - "$RESULTS" <<'PY' 2>/dev/null || echo 0
import json,sys
try:
    d=json.load(open(sys.argv[1]))
    print(len({r.get('instance_id') for r in d['rows'] if r.get('instance_id')}))
except Exception: print(0)
PY
}

echo "watchdog: start $(date) target=$TARGET"
while true; do
  # 1) keep docker reachable across daemon restarts (idempotent, cheap)
  sudo -n chmod 666 /run/docker.sock 2>/dev/null || true
  # 2) terminal?
  n=$(done_count)
  if [ "${n:-0}" -ge "$TARGET" ]; then
    echo "watchdog: DONE ($n/$TARGET) $(date)"; break
  fi
  # 3) relaunch if the run isn't alive
  if ! pgrep -f "verify_agent_grade.py --mode gold" >/dev/null 2>&1; then
    echo "watchdog: relaunching at $n/$TARGET (parallel=$PAR) $(date)"
    nohup .venv/bin/python scripts/verify_agent_grade.py --mode gold \
      --from-file sets/verified-buildable.txt \
      --out-dir runs/validation/agent-grade-t0 --parallel "$PAR" >> "$LOG" 2>&1 &
    sleep 30
  fi
  sleep 60
done
