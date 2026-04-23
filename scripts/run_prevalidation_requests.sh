#!/usr/bin/env bash
# Pre-M1 hypothesis validation — requests fixture
# Same 5-task dual-arm design as run_prevalidation.sh but on the real
# psf/requests codebase instead of the synthetic myapp fixture.
#
# Both arms use identical flags to isolate the script-vs-tools variable:
#   --system-prompt  : same minimal prompt for both (no CLAUDE.md injection)
#   --dangerously-skip-permissions : no approval gates blocking tool calls
#   --no-session-persistence : no cross-run session state

set -euo pipefail

CLAUDE=/home/vscode/.vscode-server/extensions/anthropic.claude-code-2.1.109-linux-x64/resources/native-binary/claude
FIXTURE_DIR="$(cd "$(dirname "$0")/../fixtures_requests" && pwd)"
RESULTS_DIR="$(cd "$(dirname "$0")/.." && pwd)/results_requests"
mkdir -p "$RESULTS_DIR"

COMMON_FLAGS="--output-format stream-json --verbose --no-session-persistence --dangerously-skip-permissions --system-prompt You are a helpful assistant."

TASKS=(
  "You are working in the directory: $FIXTURE_DIR

Task 1: Find all Python files in the src/requests/ directory that import 'os' or 'os.path'. List each file path and the line number of the import statement."

  "You are working in the directory: $FIXTURE_DIR

Task 2: Find all environment variable names accessed via os.environ.get() anywhere in the src/requests/ source code. List only the unique variable names."

  "You are working in the directory: $FIXTURE_DIR

Task 3: Run the test suite in tests/test_structures.py, tests/test_hooks.py, and tests/test_packages.py using pytest and give me a structured summary: total tests, how many passed, how many failed, and the exact test names of any failures."

  "You are working in the directory: $FIXTURE_DIR

Task 4: Find every file in src/requests/ that references the name 'REDIRECT_STATI'. List the source file paths only (exclude __pycache__ and .pyc files)."

  "You are working in the directory: $FIXTURE_DIR

Task 5: Add a default_timeout parameter to HTTPAdapter.__init__() in src/requests/adapters.py. Store it as self.default_timeout. In the send() method, if timeout is None, fall back to self.default_timeout. Modify the file."
)

CONSTRAINT="IMPORTANT: You must accomplish this task by writing a single Python or bash script and running it with one Bash tool call. Do not call Read, Edit, Glob, Grep, or any other tool. Put everything into one script."

echo "=== Pre-M1 Validation (requests fixture): $(date) ===" | tee "$RESULTS_DIR/run.log"
echo "Fixture: $FIXTURE_DIR" | tee -a "$RESULTS_DIR/run.log"
echo "" | tee -a "$RESULTS_DIR/run.log"

for i in "${!TASKS[@]}"; do
  TASK_NUM=$((i + 1))
  echo "--- Task $TASK_NUM ---" | tee -a "$RESULTS_DIR/run.log"

  echo "Running Task $TASK_NUM -- BASELINE..."
  $CLAUDE -p "${TASKS[$i]}" \
    $COMMON_FLAGS \
    > "$RESULTS_DIR/task${TASK_NUM}_baseline.jsonl" 2>&1
  echo "  Baseline done."

  echo "Running Task $TASK_NUM -- CONSTRAINED..."
  $CLAUDE -p "${CONSTRAINT}

${TASKS[$i]}" \
    --tools Bash,Write \
    $COMMON_FLAGS \
    > "$RESULTS_DIR/task${TASK_NUM}_constrained.jsonl" 2>&1
  echo "  Constrained done."

  echo "" | tee -a "$RESULTS_DIR/run.log"
done

echo "=== Done. Results in $RESULTS_DIR ===" | tee -a "$RESULTS_DIR/run.log"
echo ""
echo "Grade each task against oracle_requests/ files:"
echo "  oracle_requests/task1.txt  -- os imports"
echo "  oracle_requests/task2.txt  -- env var names"
echo "  oracle_requests/task3.txt  -- test summary"
echo "  oracle_requests/task4.txt  -- REDIRECT_STATI files"
echo "  oracle_requests/task5_adapters.py -- reference default_timeout impl"
