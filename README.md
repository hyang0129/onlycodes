# onlycodes

A benchmark testing whether Claude Code performs better when restricted to writing and executing code directly, rather than using its native file-system tools (Read, Grep, Glob, Edit, etc.).

## Hypothesis

Forcing the model to solve tasks by writing a single script — rather than making multiple fine-grained tool calls — should reduce turns, lower token costs, and complete tasks faster. The "only code" approach is implemented via an MCP server (`execute_code`) that provides a sandboxed Python/Bash execution environment.

## Approaches

| Arm | Description |
|---|---|
| **baseline** / **tool_rich** | All native tools available (Read, Grep, Glob, Edit, Bash, etc.) |
| **onlycode** / **code_only** | Restricted to a single `execute_code` MCP tool; must write one script per task |

SWE-bench uses `baseline` / `onlycode`; artifact-graded uses `tool_rich` / `code_only`.

## Benchmark Modes

Three benchmark modes, each targeting a different evaluation surface:

| Mode | Entry point | Task source | Grading |
|---|---|---|---|
| **SWE-bench** | `python -m swebench run` | `problems/swe/` YAML files | Test suite pass/fail |
| **Artifact-graded** | `python -m swebench artifact run` | `problems/artifact/` YAML files | Hidden Python grader |
| **Fixture (legacy)** | `./scripts/run_prevalidation.sh` | `data/fixtures/myapp/` | Oracle files in `data/oracle/` |

---

## SWE-bench Harness

The main evaluation harness. Problem instances are fetched from HuggingFace SWE-bench datasets and stored as YAML files under `problems/swe/`.

### Problem Sets

| Set | Path | Size | Description |
|---|---|---|---|
| `swebench-verified-mini` | `problems/swe/swebench-verified-mini/` | 50 | SWE-bench Verified Mini (25 django + 25 sphinx) |
| `swebench-datasci-mini` | `problems/swe/swebench-datasci-mini/` | 50 | Data-science library instances |
| `swebench-datasci-5` | `problems/swe/swebench-datasci-5/` | 5 | Small data-science smoke set |
| `adhoc` | `problems/swe/adhoc/` | varies | One-offs added without `--set` |

### CLI

```bash
# Add problem instances (fetched from HuggingFace)
python -m swebench add <instance_id>
python -m swebench add <instance_id> --set swe/swebench-verified-mini
python -m swebench add --from-file ids.txt --set swe/swebench-verified-mini --concurrency 8

# Run evaluation arms
python -m swebench run                           # both arms, all problems
python -m swebench run --arms onlycode           # onlycode arm only
python -m swebench run --arms baseline           # baseline arm only
python -m swebench run --filter django__django-16379
python -m swebench run --runs 3                  # multiple runs per arm
python -m swebench run --no-cache                # skip OverlayFS cache

# Analyze results
python -m swebench analyze summary
python -m swebench analyze summary --out results.csv

# Pathology pipeline (stages 1 → 2 → 3)
python -m swebench analyze pathology             # all three stages
python -m swebench analyze pathology --dry-run
python -m swebench analyze pathology --stage mechanical
python -m swebench analyze pathology --stage subagents
python -m swebench analyze pathology --stage synthesize
python -m swebench analyze pathology --force
python -m swebench analyze pathology --run-id my-run
python -m swebench analyze pathology --concurrency 4
```

Results go to `results_swebench/` keyed by `instance_id`. Analysis sidecars go to `results_swebench/_analysis/<run_id>/`.

### OverlayFS Cache

For large-scale or repeated runs, the harness supports an OverlayFS-backed instance cache that skips clone + venv setup on subsequent runs.

```bash
python -m swebench cache setup                   # warm all instances
python -m swebench cache setup --concurrency 8
python -m swebench cache setup --force           # rebuild existing entries
python -m swebench cache setup --filter django__django-16379
python -m swebench cache clean --filter django__django-16379
```

Cache is on by default. The harness prefers kernel overlayfs (requires `CAP_SYS_ADMIN`) and falls back to `fuse-overlayfs`. The devcontainer already grants `--cap-add=SYS_ADMIN`.

Cache layout:
```
/workspaces/.swebench-cache/
├── repos/                         # bare clones, shared across instances
└── instances/<instance_id>/
    ├── repo/                      # checkout at base_commit, scrubbed
    ├── venv/                      # python3.11 + editable install
    └── lockfile.txt               # pip freeze at cache time
```

### Pathology Vocabulary

`patterns.json` (repo root) is the canonical failure-pattern registry written by `analyze pathology --stage synthesize`. New pattern IDs are appended; existing entries are never overwritten. Edit by hand only to remove stale entries or fix descriptions.

---

## Artifact-Graded Benchmark

Purpose-built diagnostic tasks with hidden Python graders. Each task lives under `problems/artifact/<category>/<slug>/` and is graded by a `grader/hidden.py:grade(scratch_dir)` function that runs in a subprocess.

### Task Categories

| Category | Path |
|---|---|
| `algorithmic` | `problems/artifact/algorithmic/` |
| `data_processing` | `problems/artifact/data_processing/` |
| `enumeration` | `problems/artifact/enumeration/` |
| `iterative_numerical` | `problems/artifact/iterative_numerical/` |
| `stateful_reasoning` | `problems/artifact/stateful_reasoning/` |
| `verification_heavy` | `problems/artifact/verification_heavy/` |

### CLI

```bash
# Run both arms against all artifact tasks
python -m swebench artifact run

# Run specific arm or instance
python -m swebench artifact run --arms code_only
python -m swebench artifact run --arms tool_rich
python -m swebench artifact run --filter data_processing__p95_latency_easy

# Multiple runs per arm
python -m swebench artifact run --runs 3

# Resume skips already-complete runs by default
python -m swebench artifact run --no-resume
```

Results go to `results_artifact/`. Task schema is documented in [`docs/SCHEMA_ARTIFACT.md`](docs/SCHEMA_ARTIFACT.md). Architecture decisions in [`docs/adr-0001-artifact-mode.md`](docs/adr-0001-artifact-mode.md).

---

## Legacy Fixture Benchmark

The original 5-task benchmark against `data/fixtures/myapp/`. Still valid as a fast smoke test.

**Tasks:**
1. Find all Python files that import `os` or `os.path` — list file paths and line numbers
2. Find all `os.environ.get()` references that are missing from `.env.example`
3. Run the pytest suite and report total/passed/failed with exact failure names
4. Find every file containing the variable name `server_url`
5. Add a `--dry-run` flag to `myapp/cli.py` that prints intent and exits without calling `start()`

**Results:**

| Task | Baseline Cost | Only Code Cost | Savings | Baseline Time | Only Code Time | Speedup |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 — OS imports | $0.0833 | $0.0653 | 22% | 18.8s | 13.2s | 1.4× |
| 2 — Missing env vars | $0.1390 | $0.0676 | 51% | 28.4s | 7.9s | 3.6× |
| 3 — Run pytest | $0.0985 | $0.0750 | 24% | 23.4s | 11.1s | 2.1× |
| 4 — Find server_url | $0.0756 | $0.0525 | 31% | 15.9s | 10.3s | 1.5× |
| 5 — Add --dry-run | $0.1031 | $0.0796 | 23% | 8.2s | 5.0s | 1.6× |
| **Total** | **$0.4995** | **$0.3400** | **32%** | **~94.7s** | **~47.5s** | **2.0×** |

The "only code" approach was **2× faster and 32% cheaper** overall.

**Running:**
```bash
./scripts/run_prevalidation.sh          # baseline vs constrained
./scripts/run_mcp_integration_test.sh   # only-code (MCP) arm
```

Results are written as JSONL to `results/` and `results_mcp/`. Grade against `data/oracle/`.

---

## Repository Structure

```
swebench/                  # Python harness package (python -m swebench)
problems/
  swe/                     # SWE-bench problem YAML files (organized by set)
  artifact/                # Artifact-graded task trees (organized by category)
results_swebench/          # SWE-bench run outputs (JSONL, keyed by instance_id)
results_artifact/          # Artifact run outputs
docs/
  SCHEMA_ARTIFACT.md       # Normative artifact task schema
  adr-0001-artifact-mode.md
patterns.json              # Canonical failure-pattern vocabulary (pathology pipeline)
data/                      # Legacy fixture/oracle reference files (prevalidation benchmarks)
  fixtures/                #   Legacy fixture project (myapp/ + tests/)
  fixtures_requests/       #   Alternate fixture set (HTTP/requests-based tasks; gitignored)
  oracle/                  #   Ground-truth answers for legacy fixture grading
  oracle_requests/         #   Ground-truth answers for requests-fixture grading
results/                   # Legacy baseline run logs (JSONL)
results_mcp/               # Legacy only-code run logs (JSONL)
exec-server.bundle.mjs     # MCP server exposing execute_code (fast startup ~130ms)
mcp-config.json            # MCP server config for --mcp-config CLI flag
scripts/                   # Shell runners + summarize_results.py
```
