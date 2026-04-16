#!/usr/bin/env bash
# Pre-M1 hypothesis validation
# Runs 5 tasks in two arms: baseline (all tools) vs constrained (Bash only)
# Results written to results/

set -euo pipefail

CLAUDE=/home/vscode/.vscode-server/extensions/anthropic.claude-code-2.1.109-linux-x64/resources/native-binary/claude
FIXTURE_DIR="$(cd "$(dirname "$0")/fixtures" && pwd)"
RESULTS_DIR="$(cd "$(dirname "$0")" && pwd)/results"
mkdir -p "$RESULTS_DIR"

# Common flags for clean, reproducible benchmark runs:
#   --no-session-persistence  : no session saved to disk between runs
#   --dangerously-skip-permissions : no approval prompts blocking tool calls
#   --system-prompt           : override CLAUDE.md injection with neutral prompt
COMMON_FLAGS="--output-format stream-json --verbose --no-session-persistence --dangerously-skip-permissions --system-prompt You are a helpful assistant."

TASKS=(
  "You are working in the directory: $FIXTURE_DIR

Task 1: Find all Python files in the myapp/ directory that import 'os' or 'os.path'. List each file path and the line number of the import statement."

  "You are working in the directory: $FIXTURE_DIR

Task 2: Find all environment variables referenced in the myapp/ source code via os.environ.get() that do NOT appear in the .env.example file. List only the missing ones."

  "You are working in the directory: $FIXTURE_DIR

Task 3: Run the test suite in tests/ using pytest and give me a structured summary: total tests, how many passed, how many failed, and the exact test names of any failures."

  "You are working in the directory: $FIXTURE_DIR

Task 4: Find every file in myapp/ that contains the variable name 'server_url'. List the file paths only."

  "You are working in the directory: $FIXTURE_DIR

Task 5: Add a --dry-run flag to the CLI in myapp/cli.py. When --dry-run is set, the program should print what it would do and exit without calling start(). Modify the file."
)

CONSTRAINT="IMPORTANT: You must accomplish this task by writing a single Python or bash script and running it with one Bash tool call. Do not call Read, Edit, Glob, Grep, or any other tool. Put everything into one script."

echo "=== Pre-M1 Validation: $(date) ===" | tee "$RESULTS_DIR/run.log"
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
echo "Grade each task against oracle/ files:"
echo "  oracle/task1.txt  -- imports"
echo "  oracle/task2.txt  -- missing env vars"
echo "  oracle/task3.txt  -- test failures"
echo "  oracle/task4.txt  -- server_url files"
echo "  oracle/task5_cli.py -- reference --dry-run implementation"
