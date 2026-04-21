# onlycodes

Benchmark testing whether Claude Code performs better when restricted to writing/executing code vs. using native file-system tools.

## SWE-bench CLI

The evaluation harness is a Python CLI (`swebench/`) invoked via `python -m swebench`. Three subcommands:

```bash
# Add a problem instance (fetches from HuggingFace SWE-bench datasets)
python -m swebench add <instance_id>                                     # default set: swe/adhoc/
python -m swebench add <instance_id> --set swe/swebench-verified-mini    # into a named set

# Batch-add from a file of instance IDs (one per line, # comments ok; parallel HF fetch)
python -m swebench add --from-file ids.txt --set swe/swebench-verified-mini --concurrency 8

# Run evaluation arms
python -m swebench run                          # both arms, all problems (recurses into sets)
python -m swebench run --arms onlycode          # onlycode arm only
python -m swebench run --arms baseline          # baseline arm only
python -m swebench run --filter django__django-16379  # specific instance
python -m swebench run --runs 3                 # multiple runs per arm

# Analyze results — summary table
python -m swebench analyze summary
python -m swebench analyze summary --out results.csv   # write to CSV

# Analyze results — pathology pipeline (stages 1 → 2 → 3)
python -m swebench analyze pathology                   # all three stages, concurrency 8
python -m swebench analyze pathology --dry-run         # print composed commands/prompts, no claude invocations
python -m swebench analyze pathology --stage mechanical  # stage 1 only
python -m swebench analyze pathology --stage subagents   # stage 2 only
python -m swebench analyze pathology --stage synthesize  # stage 3 only
python -m swebench analyze pathology --force           # re-run even if sidecar JSON already exists
python -m swebench analyze pathology --run-id my-run   # use custom run identifier (default: UTC timestamp)
python -m swebench analyze pathology --concurrency 4   # limit parallel subagent invocations

# Cache (OverlayFS-backed environment reuse — see "SWE-bench Cache" below)
python -m swebench cache setup                         # warm every instance
python -m swebench cache setup --filter django__django-16379
python -m swebench cache clean --filter django__django-16379
python -m swebench run                                 # uses cache by default
python -m swebench run --no-cache                      # opt out of cached setup
```

Problem definitions live under `problems/swe/<set>/*.yaml` — curated sets are separated from
ad-hoc additions. Current sets:

- `problems/swe/swebench-verified-mini/` — the 50-problem [SWE-bench Verified Mini](https://hal.cs.princeton.edu/swebench_verified_mini) subset (25 django + 25 sphinx).
- `problems/swe/adhoc/` — one-offs added without specifying a set (the `add` default).

The runner recurses into every subfolder of `problems/swe/`, so additional curated sets can be
introduced simply by passing a new `--set swe/<name>` to `add`. Artifact-graded tasks live
separately under `problems/artifact/<category>/<slug>/task.yaml` and are loaded only by
`python -m swebench artifact run`. Results go to `results_swebench/` keyed by `instance_id`
(flat, regardless of set).

## patterns.json

`patterns.json` (repo root) is the canonical pathology vocabulary written by `analyze pathology`
(Stage 3 synthesize). It accumulates every distinct failure pattern observed across analysis runs.

**Location:** `/workspaces/hub_1/onlycodes/patterns.json`

**Schema** (version 1):

```jsonc
{
  "version": 1,      // integer — incremented only on breaking schema change
  "patterns": [      // list of pattern entries (may be empty)
    {
      "id": "tool-call-loop",           // slug: lowercase alnum + hyphen/underscore, 2–64 chars
      "description": "Agent enters..."  // human-readable string
    }
  ]
}
```

Tracking metadata (frequency, arm distribution, evidence refs) lives in the per-run
analysis sidecar under `results_swebench/_analysis/<run_id>/synthesizer.json`, not here.

> **Mutable.** `patterns.json` is updated in-place by `analyze pathology --stage synthesize`
> (merge semantics: new pattern ids are appended; existing entries are never overwritten).
> Edit it by hand only to remove stale entries or fix descriptions —
> any manual edits must preserve the schema above or the next pipeline run will reject the file.

Analysis sidecar output lives under:

```
results_swebench/_analysis/<run_id>/
├── mechanical/          # Stage 1: one JSON per JSONL log (mechanical flags + metrics)
├── subagents/           # Stage 2: one JSON per flagged log (subagent pathology findings)
└── synthesizer.json     # Stage 3: full synthesizer output before merge into patterns.json
```

## SWE-bench Cache

For large-scale runs (e.g. 500 instances, or the same instance re-run many times) the harness
supports an OverlayFS-backed instance cache so repeat runs skip clone + venv setup.

```
/workspaces/.swebench-cache/
├── repos/                                  # bare clones, shared across instances
└── instances/<instance_id>/
    ├── repo/                               # checkout at base_commit, scrubbed
    ├── venv/                               # python3.11 + editable install
    └── lockfile.txt                        # pip freeze at cache time
```

Warm the cache once (overnight):

```bash
python -m swebench cache setup                   # all problems
python -m swebench cache setup --concurrency 8   # parallelise setup
python -m swebench cache setup --force           # rebuild existing entries
```

Then run (cache is on by default):

```bash
python -m swebench run --filter django__django-16379
python -m swebench run --no-cache --filter django__django-16379   # opt out
```

Each evaluation mounts the cached `repo/` as the lowerdir of an OverlayFS, hands the
merged path to Claude, and on teardown unmounts + `rm -rf`s the upperdir — no git reset
needed. The venv sits outside the overlay as a sibling directory.

**Backends.** The harness prefers kernel overlayfs (requires `CAP_SYS_ADMIN` on the
container) and falls back to `fuse-overlayfs` if available. If neither works,
`--use-cache` logs a warning and falls back to the default clone+venv path. The hub-level
devcontainer already grants `--cap-add=SYS_ADMIN`.

**Integrity check.** Before mounting, the harness diffs the venv's current `pip freeze`
against the cached lockfile. If they drift (e.g. a prior run leaked a pip install), the
cache entry is rebuilt automatically.

**Scrub list.** Before caching, the harness removes `__pycache__/`, `*.pyc`/`*.pyo`, `*.swp`,
`.claude/`, `*.egg-info/`, and stale `.git/COMMIT_EDITMSG`/`MERGE_MSG`/`FETCH_HEAD`
to prevent context leakage into later runs. `.egg-info` is regenerated post-mount by
re-running `pip install -e .` (no network).

## MCP Server

`exec-server.bundle.mjs` — the MCP server exposing `execute_code`. Config in `mcp-config.json`.

## Legacy Scripts

`run_prevalidation.sh`, `run_mcp_integration_test.sh` — original fixture-based benchmarks (not SWE-bench). Still valid for the 5-task fixture suite in `fixtures/`.
