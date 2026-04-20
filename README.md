# onlycodes

A benchmark testing whether Claude Code performs better when restricted to writing and executing code directly, rather than using its native file-system tools (Read, Grep, Glob, Edit, etc.).

## Hypothesis

Forcing the model to solve tasks by writing a single script — rather than making multiple fine-grained tool calls — should reduce turns, lower token costs, and complete tasks faster. The "only code" approach is implemented via an MCP server (`execute_code`) that provides a sandboxed Python/Bash execution environment.

## Approaches

| Approach | Description |
|---|---|
| **Baseline** | All native tools available (Read, Grep, Glob, Edit, Bash, etc.) |
| **Only code (no tools)** | Restricted to a single `execute_code` MCP tool; must write one script per task |

## Benchmark Tasks

Five tasks against a shared Python fixture project (`fixtures/myapp/`):

1. Find all Python files that import `os` or `os.path` — list file paths and line numbers
2. Find all `os.environ.get()` references that are missing from `.env.example`
3. Run the pytest suite and report total/passed/failed with exact failure names
4. Find every file containing the variable name `server_url`
5. Add a `--dry-run` flag to `myapp/cli.py` that prints intent and exits without calling `start()`

## Results

| Task | Baseline Cost | Only Code Cost | Savings | Baseline Time | Only Code Time | Speedup |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 — OS imports | $0.0833 | $0.0653 | 22% | 18.8s | 13.2s | 1.4× |
| 2 — Missing env vars | $0.1390 | $0.0676 | 51% | 28.4s | 7.9s | 3.6× |
| 3 — Run pytest | $0.0985 | $0.0750 | 24% | 23.4s | 11.1s | 2.1× |
| 4 — Find server_url | $0.0756 | $0.0525 | 31% | 15.9s | 10.3s | 1.5× |
| 5 — Add --dry-run | $0.1031 | $0.0796 | 23% | 8.2s | 5.0s | 1.6× |
| **Total** | **$0.4995** | **$0.3400** | **32%** | **~94.7s** | **~47.5s** | **2.0×** |

All 10 runs completed successfully (100% task success rate).

The "only code" approach was **2× faster and 32% cheaper** overall. Task 2 shows the largest gap: baseline hit a permission denial mid-task, retried across 13 turns, and accumulated 175k cache-read tokens vs 7.5k for the single-shot script approach.

## Repository Structure

```
fixtures/          # Benchmark fixture project (myapp/ + tests/)
fixtures_requests/ # Alternate fixture set (HTTP/requests-based tasks)
oracle/            # Ground-truth answers for grading each task
results/           # Baseline vs constrained run logs (JSONL)
results_mcp/       # Only-code (MCP) run logs (JSONL)
exec-server.js     # MCP server exposing execute_code tool (stdio transport)
exec-server.bundle.mjs  # Bundled version for fast startup (~130ms vs ~3.9s)
mcp-config.json    # MCP server config for --mcp-config CLI flag
run_prevalidation.sh       # Baseline vs constrained benchmark runner
run_mcp_integration_test.sh  # Only-code (MCP) benchmark runner
```

## Running the Benchmark

**Baseline (all tools):**
```bash
./run_prevalidation.sh
```

**Only code (MCP):**
```bash
./run_mcp_integration_test.sh
```

Results are written as JSONL streams to `results/` and `results_mcp/` respectively. Grade against the oracle files in `oracle/`.

## Artifact-Graded Mode

A second benchmark mode (purpose-built diagnostic tasks with hidden graders, landing under epic [#92](https://github.com/hyang0129/onlycodes/issues/92)) is specified in [`docs/SCHEMA_ARTIFACT.md`](docs/SCHEMA_ARTIFACT.md). That document is the normative task schema — task authors and harness implementers should read it before drafting tasks or loader code. Harness CLI wiring lands separately (see [`docs/adr-0001-artifact-mode.md`](docs/adr-0001-artifact-mode.md)).
