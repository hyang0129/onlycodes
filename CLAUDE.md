# onlycodes

Benchmark testing whether Claude Code performs better when restricted to writing/executing code vs. using native file-system tools.

## SWE-bench CLI

The evaluation harness is a Python CLI (`swebench/`) invoked via `python -m swebench`. Three subcommands:

```bash
# Add a problem instance (fetches from HuggingFace SWE-bench datasets)
python -m swebench add <instance_id>

# Run evaluation arms
python -m swebench run                          # both arms, all problems
python -m swebench run --arms onlycode          # onlycode arm only
python -m swebench run --arms baseline          # baseline arm only
python -m swebench run --filter django__django-16379  # specific instance
python -m swebench run --runs 3                 # multiple runs per arm

# Analyze results
python -m swebench analyze
```

Problem definitions live in `problems/*.yaml`. Results go to `results_swebench/`.

## MCP Server

`exec-server.bundle.mjs` — the MCP server exposing `execute_code`. Config in `mcp-config.json`.

## Legacy Scripts

`run_prevalidation.sh`, `run_mcp_integration_test.sh` — original fixture-based benchmarks (not SWE-bench). Still valid for the 5-task fixture suite in `fixtures/`.
