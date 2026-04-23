#!/usr/bin/env bash
# MCP Integration Test
# Runs 5 tasks using only the execute_code MCP tool (codebox).
# Results written to results_mcp/

set -euo pipefail

CLAUDE=/home/vscode/.vscode-server/extensions/anthropic.claude-code-2.1.109-linux-x64/resources/native-binary/claude
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
FIXTURE_DIR="$REPO_ROOT/fixtures"
RESULTS_DIR="$REPO_ROOT/results_mcp"
MCP_CONFIG="$REPO_ROOT/mcp-config.json"  # points to exec-server.bundle.mjs (bundled for fast startup)
mkdir -p "$RESULTS_DIR"

# Common flags for clean, reproducible runs:
#   --no-session-persistence       : no session saved to disk between runs
#   --dangerously-skip-permissions : no approval prompts blocking tool calls
#   --system-prompt                : override CLAUDE.md injection with neutral prompt
#   --tools                        : restrict to the execute_code MCP tool only
COMMON_FLAGS="--output-format stream-json --verbose --no-session-persistence --dangerously-skip-permissions --mcp-config $MCP_CONFIG --strict-mcp-config --system-prompt You are a helpful assistant. --tools mcp__codebox__execute_code"

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

CONSTRAINT="IMPORTANT: You must accomplish this task using only the execute_code MCP tool. Write a single Python or bash script and run it with one execute_code call. Do not use any other tool."

echo "=== MCP Integration Test: $(date) ===" | tee "$RESULTS_DIR/run.log"
echo "Fixture: $FIXTURE_DIR" | tee -a "$RESULTS_DIR/run.log"
echo "" | tee -a "$RESULTS_DIR/run.log"

for i in "${!TASKS[@]}"; do
  TASK_NUM=$((i + 1))
  echo "--- Task $TASK_NUM ---" | tee -a "$RESULTS_DIR/run.log"

  echo "Running Task $TASK_NUM -- MCP..."
  $CLAUDE -p "${CONSTRAINT}

${TASKS[$i]}" \
    $COMMON_FLAGS \
    > "$RESULTS_DIR/task${TASK_NUM}_mcp.jsonl" 2>&1
  echo "  Done." | tee -a "$RESULTS_DIR/run.log"

  echo "" | tee -a "$RESULTS_DIR/run.log"
done

echo "=== Done. Results in $RESULTS_DIR ===" | tee -a "$RESULTS_DIR/run.log"
echo ""
echo "Grade each task against oracle/ files:"
echo "  oracle/task1.txt       -- imports"
echo "  oracle/task2.txt       -- missing env vars"
echo "  oracle/task3.txt       -- test failures"
echo "  oracle/task4.txt       -- server_url files"
echo "  oracle/task5_cli.py    -- reference --dry-run implementation"
