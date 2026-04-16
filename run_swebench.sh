#!/usr/bin/env bash
# SWE-bench smoke test: baseline vs. onlycode comparison
# Runs selected SWE-bench instances in two arms — baseline (all built-in tools)
# and onlycode (MCP execute_code tool only, no built-ins).
#
# Usage:
#   ./run_swebench.sh [problems_file] [runs_per_arm]
#
# Defaults:
#   problems_file = swebench_problems.txt
#   runs_per_arm  = 1
#
# Architecture is parametric: positional parameters support future expansion
# without structural changes.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROBLEMS_FILE="${1:-${SCRIPT_DIR}/swebench_problems.txt}"
RUNS_PER_ARM="${2:-1}"
if [[ ! "$RUNS_PER_ARM" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: runs_per_arm must be a positive integer, got: '$RUNS_PER_ARM'" >&2
  exit 1
fi
RESULTS_DIR="${SCRIPT_DIR}/results_swebench"
CLONE_BASE="/tmp/swebench"
MCP_CONFIG="${SCRIPT_DIR}/mcp-config.json"

mkdir -p "$RESULTS_DIR" "$CLONE_BASE"

# Locate claude binary — same approach as run_prevalidation.sh
CLAUDE="${CLAUDE:-$(command -v claude 2>/dev/null || echo "")}"
if [[ -z "$CLAUDE" ]]; then
  # Try VS Code extension path
  for ext_dir in /home/vscode/.vscode-server/extensions/anthropic.claude-code-*-linux-x64; do
    candidate="${ext_dir}/resources/native-binary/claude"
    if [[ -x "$candidate" ]]; then
      CLAUDE="$candidate"
      break
    fi
  done
fi

if [[ -z "$CLAUDE" || ! -x "$CLAUDE" ]]; then
  echo "ERROR: claude binary not found. Set CLAUDE= or install Claude Code." >&2
  exit 1
fi

echo "=== SWE-bench Evaluation: $(date) ===" | tee "$RESULTS_DIR/run.log"
echo "Problems file: $PROBLEMS_FILE" | tee -a "$RESULTS_DIR/run.log"
echo "Runs per arm:  $RUNS_PER_ARM" | tee -a "$RESULTS_DIR/run.log"
echo "Claude binary: $CLAUDE" | tee -a "$RESULTS_DIR/run.log"
echo "" | tee -a "$RESULTS_DIR/run.log"

# --------------------------------------------------------------------------
# Helper: run one arm (baseline or onlycode) for one instance
# --------------------------------------------------------------------------
run_arm() {
  local INSTANCE="$1"
  local ARM="$2"
  local TOOLS_FLAGS="$3"
  local SYSTEM_PROMPT="$4"
  local RUN_IDX="$5"
  local REPO_DIR="$6"
  local BASE_COMMIT="$7"
  local TEST_CMD="$8"
  local PROBLEM_TEXT="$9"
  local VENV_DIR="${10}"

  echo "  [${ARM} run ${RUN_IDX}] Starting..." | tee -a "$RESULTS_DIR/run.log"

  # Reset repo to base commit before each arm run
  git -C "$REPO_DIR" checkout "$BASE_COMMIT" --force --quiet 2>/dev/null
  git -C "$REPO_DIR" clean -fd --quiet 2>/dev/null

  # Apply test-only patch (SWE-bench style: agent sees failing tests, must fix implementation)
  local TEST_PATCH="${SCRIPT_DIR}/patches/${INSTANCE}_tests.patch"
  if [[ -f "$TEST_PATCH" ]]; then
    git -C "$REPO_DIR" apply "$TEST_PATCH" 2>/dev/null \
      && echo "  [${ARM} run ${RUN_IDX}] Applied test patch." | tee -a "$RESULTS_DIR/run.log" \
      || echo "  [${ARM} run ${RUN_IDX}] WARNING: test patch failed to apply." | tee -a "$RESULTS_DIR/run.log"
  fi

  # Isolated Claude config: only credentials, no settings/skills/memories
  local EVAL_CFG
  EVAL_CFG=$(mktemp -d /tmp/claude-eval-XXXXXX)
  if [[ -f ~/.claude/.credentials.json ]]; then
    cp ~/.claude/.credentials.json "$EVAL_CFG/"
  fi
  if [[ -f ~/.claude/.claude.json ]]; then
    cp ~/.claude/.claude.json "$EVAL_CFG/"
  fi

  local RESULT_FILE="${RESULTS_DIR}/${INSTANCE}_${ARM}_run${RUN_IDX}.jsonl"

  # Generate per-run MCP config with cwd set to the target repo
  local EFFECTIVE_MCP_CONFIG="$MCP_CONFIG"
  if [[ -f "$MCP_CONFIG" ]]; then
    EFFECTIVE_MCP_CONFIG=$(mktemp /tmp/mcp-config-XXXXXX.json)
    jq --arg cwd "$REPO_DIR" '.mcpServers.codebox.cwd = $cwd' "$MCP_CONFIG" > "$EFFECTIVE_MCP_CONFIG"
  fi
  # Replace MCP_CONFIG path in TOOLS_FLAGS with the per-run config
  local EFFECTIVE_TOOLS_FLAGS="${TOOLS_FLAGS//${MCP_CONFIG}/${EFFECTIVE_MCP_CONFIG}}"

  # Run claude with timing
  local START_TIME
  START_TIME=$(date +%s)

  # Build the full prompt including the problem statement and repo path
  local FULL_PROMPT
  FULL_PROMPT="You are working in the repository at: ${REPO_DIR}

Fix the following bug. Make the minimal change needed.

${PROBLEM_TEXT}"

  # shellcheck disable=SC2086
  CLAUDE_CONFIG_DIR="$EVAL_CFG" \
    "$CLAUDE" -p "$FULL_PROMPT" \
    --model claude-sonnet-4-6 \
    --cwd "$REPO_DIR" \
    --system-prompt "$SYSTEM_PROMPT" \
    $EFFECTIVE_TOOLS_FLAGS \
    --dangerously-skip-permissions \
    --no-session-persistence \
    --output-format stream-json \
    --verbose \
    > "$RESULT_FILE" 2>&1 || true

  local END_TIME
  END_TIME=$(date +%s)
  local WALL_SECS=$(( END_TIME - START_TIME ))

  rm -rf "$EVAL_CFG"
  if [[ "$EFFECTIVE_MCP_CONFIG" != "$MCP_CONFIG" ]]; then
    rm -f "$EFFECTIVE_MCP_CONFIG"
  fi

  # Run the test suite to get pass/fail verdict
  local TEST_RESULT_FILE="${RESULTS_DIR}/${INSTANCE}_${ARM}_run${RUN_IDX}_test.txt"

  echo "  [${ARM} run ${RUN_IDX}] Running test suite..." | tee -a "$RESULTS_DIR/run.log"

  # Run test command from the repo dir using the venv python
  (
    cd "$REPO_DIR"
    # TEST_CMD starts with "python ..." — replace leading python with venv python
    local VENV_TEST_CMD="${TEST_CMD/#python/${VENV_DIR}/bin/python}"
    # shellcheck disable=SC2086
    if $VENV_TEST_CMD > "$TEST_RESULT_FILE" 2>&1; then
      echo "PASS" >> "$TEST_RESULT_FILE"
      echo "  [${ARM} run ${RUN_IDX}] Tests: PASS (${WALL_SECS}s wall)" | tee -a "$RESULTS_DIR/run.log"
    else
      echo "FAIL" >> "$TEST_RESULT_FILE"
      echo "  [${ARM} run ${RUN_IDX}] Tests: FAIL (${WALL_SECS}s wall)" | tee -a "$RESULTS_DIR/run.log"
    fi
  )

  # Extract cost and turns from stream-json output
  local COST TURNS
  COST=$(grep -o '"total_cost_usd":[0-9.]*' "$RESULT_FILE" 2>/dev/null | tail -1 | cut -d: -f2 || echo "N/A")
  TURNS=$(grep -o '"num_turns":[0-9]*' "$RESULT_FILE" 2>/dev/null | tail -1 | cut -d: -f2 || echo "N/A")

  echo "  [${ARM} run ${RUN_IDX}] Cost: \$${COST}, Turns: ${TURNS}, Wall: ${WALL_SECS}s" \
    | tee -a "$RESULTS_DIR/run.log"
}

# --------------------------------------------------------------------------
# Main loop: iterate over problems
# --------------------------------------------------------------------------
while IFS=$'\t ' read -r INSTANCE BASE_COMMIT REPO_SLUG TEST_CMD_REST || [[ -n "$INSTANCE" ]]; do
  # Skip comments and blank lines
  [[ "$INSTANCE" =~ ^#.*$ || -z "$INSTANCE" ]] && continue

  # TEST_CMD_REST may contain spaces — reassemble from the 4th field onward
  # Re-read the line to get the full test command
  TEST_CMD="$TEST_CMD_REST"

  echo "--- Instance: $INSTANCE ---" | tee -a "$RESULTS_DIR/run.log"
  echo "  Repo: $REPO_SLUG" | tee -a "$RESULTS_DIR/run.log"
  echo "  Base commit: $BASE_COMMIT" | tee -a "$RESULTS_DIR/run.log"
  echo "  Test cmd: $TEST_CMD" | tee -a "$RESULTS_DIR/run.log"

  REPO_DIR="${CLONE_BASE}/${INSTANCE}"

  # --- Clone repo at base commit ---
  if [[ ! -d "$REPO_DIR/.git" ]]; then
    echo "  Cloning ${REPO_SLUG}..." | tee -a "$RESULTS_DIR/run.log"
    gh repo clone "${REPO_SLUG}" "$REPO_DIR" -- --quiet 2>&1 \
      | tee -a "$RESULTS_DIR/run.log" || true
  fi

  git -C "$REPO_DIR" checkout "$BASE_COMMIT" --force --quiet

  # --- Set up venv once per instance (outside REPO_DIR so git clean -fd doesn't wipe it) ---
  VENV_DIR="${CLONE_BASE}/venvs/${INSTANCE}"
  if [[ ! -d "$VENV_DIR" ]]; then
    echo "  Setting up venv..." | tee -a "$RESULTS_DIR/run.log"
    python3.11 -m venv "$VENV_DIR"
    # Install the project in editable mode
    "${VENV_DIR}/bin/pip" install --quiet -e "${REPO_DIR}" 2>&1 \
      | tee -a "$RESULTS_DIR/run.log" || true
  fi

  # --- Build the problem statement ---
  # TODO: When scaling to 20 problems, fetch problem_statement from SWE-bench
  # dataset via: python3 -c "from datasets import load_dataset; ..."
  # For the smoke test, the problem statement is hardcoded for the single instance.
  if [[ "$INSTANCE" != "django__django-16379" ]]; then
    echo "  WARNING: PROBLEM_TEXT is hardcoded for django__django-16379." >&2
    echo "           Results for ${INSTANCE} may be invalid." >&2
    echo "           Implement dynamic problem_statement fetching (see TODO above)." >&2
    echo "  WARNING: PROBLEM_TEXT hardcoded — ${INSTANCE} results may be invalid" \
      | tee -a "$RESULTS_DIR/run.log"
  fi
  PROBLEM_TEXT="The following tests are failing:

  cache.tests.FileBasedCacheTests.test_has_key_race_handling
  cache.tests.FileBasedCachePathLibTests.test_has_key_race_handling

Fix the source code so these tests pass. Do not modify the test files."

  # --- Run both arms ---
  for RUN in $(seq 1 "$RUNS_PER_ARM"); do
    echo "" | tee -a "$RESULTS_DIR/run.log"

    # Baseline arm: all default tools
    run_arm "$INSTANCE" "baseline" "" \
      "You are a helpful assistant." \
      "$RUN" "$REPO_DIR" "$BASE_COMMIT" "$TEST_CMD" "$PROBLEM_TEXT" "$VENV_DIR"

    # Onlycode arm: MCP execute_code tool only, no built-in tools
    # run_arm() resets the repo to BASE_COMMIT as its first action — no explicit reset needed here.
    # run_arm() generates a per-instance MCP config with cwd=$REPO_DIR so the MCP server
    # runs in the target repo, matching the baseline arm's working directory.
    run_arm "$INSTANCE" "onlycode" "--mcp-config ${MCP_CONFIG} --strict-mcp-config --tools mcp__codebox__execute_code" \
      "You are a helpful assistant." \
      "$RUN" "$REPO_DIR" "$BASE_COMMIT" "$TEST_CMD" "$PROBLEM_TEXT" "$VENV_DIR"
  done

  echo "" | tee -a "$RESULTS_DIR/run.log"
done < "$PROBLEMS_FILE"

# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------
echo "=== Done. Results in ${RESULTS_DIR}/ ===" | tee -a "$RESULTS_DIR/run.log"
echo ""
echo "Result files per instance per arm:"
echo "  *_baseline_run*.jsonl   — stream-json output from baseline arm"
echo "  *_onlycode_run*.jsonl   — stream-json output from onlycode arm"
echo "  *_test.txt              — test suite output + PASS/FAIL verdict"
echo ""
echo "To generate summary: review *_test.txt files for PASS/FAIL verdicts,"
echo "and grep for total_cost_usd / num_turns in the .jsonl files."
