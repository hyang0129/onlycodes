# onlycodes

Benchmark testing whether Claude Code performs better when restricted to writing/executing code vs. using native file-system tools.

## SWE-bench CLI

The evaluation harness is a Python CLI (`swebench/`) invoked via `python -m swebench`. Three subcommands:

```bash
# Add a problem instance (fetches from HuggingFace SWE-bench datasets)
python -m swebench add <instance_id>                                 # default set: adhoc/
python -m swebench add <instance_id> --set swebench-verified-mini    # into a named set

# Batch-add from a file of instance IDs (one per line, # comments ok; parallel HF fetch)
python -m swebench add --from-file ids.txt --set swebench-verified-mini --concurrency 8

# Run evaluation arms
python -m swebench run                          # both arms, all problems (recurses into sets)
python -m swebench run --arms onlycode          # onlycode arm only
python -m swebench run --arms baseline          # baseline arm only
python -m swebench run --filter django__django-16379  # specific instance
python -m swebench run --runs 3                 # multiple runs per arm

# Analyze results
python -m swebench analyze
```

Problem definitions live under `problems/<set>/*.yaml` — curated sets are separated from
ad-hoc additions. Current sets:

- `problems/swebench-verified-mini/` — the 50-problem [SWE-bench Verified Mini](https://hal.cs.princeton.edu/swebench_verified_mini) subset (25 django + 25 sphinx).
- `problems/adhoc/` — one-offs added without specifying a set (the `add` default).

The runner recurses into every subfolder of `problems/`, so additional curated sets can be
introduced simply by passing a new `--set <name>` to `add`. Results go to `results_swebench/`
keyed by `instance_id` (flat, regardless of set).

## MCP Server

`exec-server.bundle.mjs` — the MCP server exposing `execute_code`. Config in `mcp-config.json`.

## Legacy Scripts

`run_prevalidation.sh`, `run_mcp_integration_test.sh` — original fixture-based benchmarks (not SWE-bench). Still valid for the 5-task fixture suite in `fixtures/`.
