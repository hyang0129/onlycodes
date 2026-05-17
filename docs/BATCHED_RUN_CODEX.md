# Batched Codex CLI Run

Same 100 problems and 9-batch structure as [BATCHED_RUN_SWE.md](BATCHED_RUN_SWE.md), run with the
`codex_cli` agent surface instead of `claude_code`. Three seeds for variance estimation.

## Key differences from the Claude batched run

| Aspect | Claude runs | Codex runs |
|--------|-------------|------------|
| `--agent-surface` | `claude_code` (default) | `codex_cli` |
| Auth source | `~/.claude/.credentials.json` | `~/.codex/auth.json` |
| Tool restriction mechanism | CLI flags (`--tools`, `--disallowedTools`) | `config.toml` `[features]` block |
| Cost reporting | Real USD from `total_cost_usd` | Estimated from token counts × `codex_prices.toml` |
| Useful arms | `baseline`, `onlycode`, `bash_only` | `baseline`, `onlycode` only (`bash_only` = no-op for Codex) |
| Output dirs | `runs/swebench/full_run_seed_N/` | `runs/swebench/codex_gpt55_seed_N/` |

**Why separate output dirs:** the resume index is keyed on `(instance_id, arm, run_idx)` in
filename. If Claude and Codex results share a dir, Claude's completed `baseline` run blocks
the Codex `baseline` run. Always use a Codex-specific output dir.

**Why skip `bash_only`:** `CodexRunner` enforces restrictions via `config.toml` `[features]`.
Only the `onlycode` arm adds extra feature flags (`browser_use = false`,
`computer_use = false`). The `bash_only` arm produces config identical to `baseline` for
Codex, so running it wastes quota without adding signal.

## Sets

| Set | Problems | Repos | Batches |
|---|---|---|---|
| swebench-verified-mini | 50 | Django (25), Sphinx (25) | V1–V4 |
| swebench-datasci-mini | 50 | scikit-learn (15), matplotlib (12), xarray (8), sympy (7), seaborn (5), astropy (3) | D1–D5 |

## Seeds

| Seed | Output dir | Status |
|---|---|---|
| seed_1 | `runs/swebench/codex_gpt55_seed_1/` | not started |
| seed_2 | `runs/swebench/codex_gpt55_seed_2/` | not started |
| seed_3 | `runs/swebench/codex_gpt55_seed_3/` | not started |

## Prerequisites

Run these checks before starting any batch. All three must pass.

### 1. Auth

```bash
ls ~/.codex/auth.json   # must exist — CodexRunner.verify_auth() checks this exact path
```

A missing `auth.json` surfaces immediately at preflight (`FileNotFoundError`) before any
instance runs. An expired token only surfaces at runtime when Codex rejects the first API call.

### 2. Exec-server bundle

```bash
ls /workspaces/hub_1/onlycodes/exec_server/dist/exec-server.bundle.mjs
```

If missing, build it first:

```bash
cd /workspaces/hub_1/onlycodes/exec_server && npm run build
```

### 3. Codex binary and Node

```bash
which codex   # must print a path
which node    # must print a path
```

Install codex if missing: `npm install -g @openai/codex`

### Preflight verification (run one instance)

The harness calls `CodexRunner.preflight()` automatically before the first arm. To verify
all three conditions before committing to a full batch, run a single-instance dry-run:

```bash
cd /workspaces/hub_1/onlycodes
source .venv/bin/activate
export SWEBENCH_CACHE_ROOT=/tmp/swebench-cache
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir /tmp/codex-preflight-test \
  --arms baseline \
  --parallel 1 \
  --filter "django__django-11790"
```

If preflight passes and the run starts, the setup is valid. Ctrl-C after the first arm begins.

## Common setup

```bash
cd /workspaces/hub_1/onlycodes
source .venv/bin/activate
export SWEBENCH_CACHE_ROOT=/tmp/swebench-cache
```

## Cache setup (shared with Claude runs)

The OverlayFS cache is agent-agnostic. If `BATCHED_RUN_SWE.md` cache setup has already been
run on this machine, skip this section.

```bash
# Heavy sklearn instances (~18 min each to compile from scratch) — warm up before D2:
python -m swebench cache setup \
  --filter "scikit-learn__scikit-learn-24677,scikit-learn__scikit-learn-25694" \
  --concurrency 1

# Optional — cache everything else for faster arm-to-arm resets:
python -m swebench cache setup --concurrency 4
```

## Cost estimation notes

Codex CLI does not emit a USD cost field. `extract_metadata` estimates cost from
`turn.completed` token-usage events multiplied by prices in `swebench/codex_prices.toml`.

- Prices are loaded per-file at result parse time (a manual edit during a long run takes
  effect immediately without restart).
- An unknown `--codex-model` slug degrades to `cost=None` in all result files — check
  `codex_prices.toml` before adding a new model.
- Costs appear prefixed `~$` in the harness output and summary CSV to flag the estimate.

Current price table (verified 2026-05-16):

| Model slug | Input $/1M | Cached input $/1M | Output $/1M |
|---|---|---|---|
| `gpt-5.5` | $5.00 | $0.50 | $30.00 |
| `gpt-5.4` | $2.50 | $0.25 | $15.00 |
| `gpt-5.4-mini` | $0.75 | $0.075 | $4.50 |

---

## Seed 1 — `runs/swebench/codex_gpt55_seed_1/`

### Batch V1 — Django part 1 (13 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_1 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "django__django-11790,django__django-11815,django__django-11848,django__django-11880,django__django-11885,django__django-11951,django__django-11964,django__django-11999,django__django-12039,django__django-12050,django__django-12143,django__django-12155,django__django-12193"
```

### Batch V2 — Django part 2 (12 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_1 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "django__django-12209,django__django-12262,django__django-12273,django__django-12276,django__django-12304,django__django-12308,django__django-12325,django__django-12406,django__django-12708,django__django-12713,django__django-12774,django__django-9296"
```

### Batch V3 — Sphinx part 1 (13 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_1 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "sphinx-doc__sphinx-10323,sphinx-doc__sphinx-10435,sphinx-doc__sphinx-10466,sphinx-doc__sphinx-10673,sphinx-doc__sphinx-11510,sphinx-doc__sphinx-7590,sphinx-doc__sphinx-7748,sphinx-doc__sphinx-7757,sphinx-doc__sphinx-7985,sphinx-doc__sphinx-8035,sphinx-doc__sphinx-8056,sphinx-doc__sphinx-8265,sphinx-doc__sphinx-8269"
```

### Batch V4 — Sphinx part 2 (12 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_1 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "sphinx-doc__sphinx-8475,sphinx-doc__sphinx-8548,sphinx-doc__sphinx-8551,sphinx-doc__sphinx-8638,sphinx-doc__sphinx-8721,sphinx-doc__sphinx-9229,sphinx-doc__sphinx-9230,sphinx-doc__sphinx-9281,sphinx-doc__sphinx-9320,sphinx-doc__sphinx-9367,sphinx-doc__sphinx-9461,sphinx-doc__sphinx-9698"
```

### Batch D1 — scikit-learn part 1 (8 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_1 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "scikit-learn__scikit-learn-10427,scikit-learn__scikit-learn-10803,scikit-learn__scikit-learn-11206,scikit-learn__scikit-learn-11596,scikit-learn__scikit-learn-12704,scikit-learn__scikit-learn-13013,scikit-learn__scikit-learn-13283,scikit-learn__scikit-learn-13496"
```

### Batch D2 — scikit-learn part 2 (7 problems)

Warm up the heavy sklearn instances before this batch if not already cached:

```bash
python -m swebench cache setup \
  --filter "scikit-learn__scikit-learn-24677,scikit-learn__scikit-learn-25694" \
  --concurrency 1
```

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_1 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "scikit-learn__scikit-learn-13864,scikit-learn__scikit-learn-14125,scikit-learn__scikit-learn-14710,scikit-learn__scikit-learn-15094,scikit-learn__scikit-learn-24677,scikit-learn__scikit-learn-25694,scikit-learn__scikit-learn-3840"
```

### Batch D3 — matplotlib (12 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_1 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "matplotlib__matplotlib-13859,matplotlib__matplotlib-19763,matplotlib__matplotlib-21042,matplotlib__matplotlib-22767,matplotlib__matplotlib-23088,matplotlib__matplotlib-23476,matplotlib__matplotlib-24177,matplotlib__matplotlib-24637,matplotlib__matplotlib-25126,matplotlib__matplotlib-25442,matplotlib__matplotlib-25772,matplotlib__matplotlib-26160"
```

### Batch D4 — xarray + astropy (11 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_1 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "pydata__xarray-2905,pydata__xarray-3520,pydata__xarray-4075,pydata__xarray-4629,pydata__xarray-4911,pydata__xarray-5455,pydata__xarray-6601,pydata__xarray-7003,astropy__astropy-12962,astropy__astropy-13842,astropy__astropy-6938"
```

### Batch D5 — sympy + seaborn (12 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_1 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "sympy__sympy-11232,sympy__sympy-13259,sympy__sympy-14180,sympy__sympy-15976,sympy__sympy-17318,sympy__sympy-19016,sympy__sympy-21596,mwaskom__seaborn-2389,mwaskom__seaborn-2813,mwaskom__seaborn-2946,mwaskom__seaborn-3069,mwaskom__seaborn-3202"
```

### Seed 1 analysis

```bash
python -m swebench analyze summary \
  --results-dir runs/swebench/codex_gpt55_seed_1 \
  --out runs/swebench/codex_gpt55_seed_1/summary.csv
```

---

## Seed 2 — `runs/swebench/codex_gpt55_seed_2/`

### Batch V1 — Django part 1 (13 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_2 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "django__django-11790,django__django-11815,django__django-11848,django__django-11880,django__django-11885,django__django-11951,django__django-11964,django__django-11999,django__django-12039,django__django-12050,django__django-12143,django__django-12155,django__django-12193"
```

### Batch V2 — Django part 2 (12 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_2 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "django__django-12209,django__django-12262,django__django-12273,django__django-12276,django__django-12304,django__django-12308,django__django-12325,django__django-12406,django__django-12708,django__django-12713,django__django-12774,django__django-9296"
```

### Batch V3 — Sphinx part 1 (13 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_2 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "sphinx-doc__sphinx-10323,sphinx-doc__sphinx-10435,sphinx-doc__sphinx-10466,sphinx-doc__sphinx-10673,sphinx-doc__sphinx-11510,sphinx-doc__sphinx-7590,sphinx-doc__sphinx-7748,sphinx-doc__sphinx-7757,sphinx-doc__sphinx-7985,sphinx-doc__sphinx-8035,sphinx-doc__sphinx-8056,sphinx-doc__sphinx-8265,sphinx-doc__sphinx-8269"
```

### Batch V4 — Sphinx part 2 (12 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_2 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "sphinx-doc__sphinx-8475,sphinx-doc__sphinx-8548,sphinx-doc__sphinx-8551,sphinx-doc__sphinx-8638,sphinx-doc__sphinx-8721,sphinx-doc__sphinx-9229,sphinx-doc__sphinx-9230,sphinx-doc__sphinx-9281,sphinx-doc__sphinx-9320,sphinx-doc__sphinx-9367,sphinx-doc__sphinx-9461,sphinx-doc__sphinx-9698"
```

### Batch D1 — scikit-learn part 1 (8 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_2 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "scikit-learn__scikit-learn-10427,scikit-learn__scikit-learn-10803,scikit-learn__scikit-learn-11206,scikit-learn__scikit-learn-11596,scikit-learn__scikit-learn-12704,scikit-learn__scikit-learn-13013,scikit-learn__scikit-learn-13283,scikit-learn__scikit-learn-13496"
```

### Batch D2 — scikit-learn part 2 (7 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_2 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "scikit-learn__scikit-learn-13864,scikit-learn__scikit-learn-14125,scikit-learn__scikit-learn-14710,scikit-learn__scikit-learn-15094,scikit-learn__scikit-learn-24677,scikit-learn__scikit-learn-25694,scikit-learn__scikit-learn-3840"
```

### Batch D3 — matplotlib (12 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_2 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "matplotlib__matplotlib-13859,matplotlib__matplotlib-19763,matplotlib__matplotlib-21042,matplotlib__matplotlib-22767,matplotlib__matplotlib-23088,matplotlib__matplotlib-23476,matplotlib__matplotlib-24177,matplotlib__matplotlib-24637,matplotlib__matplotlib-25126,matplotlib__matplotlib-25442,matplotlib__matplotlib-25772,matplotlib__matplotlib-26160"
```

### Batch D4 — xarray + astropy (11 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_2 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "pydata__xarray-2905,pydata__xarray-3520,pydata__xarray-4075,pydata__xarray-4629,pydata__xarray-4911,pydata__xarray-5455,pydata__xarray-6601,pydata__xarray-7003,astropy__astropy-12962,astropy__astropy-13842,astropy__astropy-6938"
```

### Batch D5 — sympy + seaborn (12 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_2 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "sympy__sympy-11232,sympy__sympy-13259,sympy__sympy-14180,sympy__sympy-15976,sympy__sympy-17318,sympy__sympy-19016,sympy__sympy-21596,mwaskom__seaborn-2389,mwaskom__seaborn-2813,mwaskom__seaborn-2946,mwaskom__seaborn-3069,mwaskom__seaborn-3202"
```

### Seed 2 analysis

```bash
python -m swebench analyze summary \
  --results-dir runs/swebench/codex_gpt55_seed_2 \
  --out runs/swebench/codex_gpt55_seed_2/summary.csv
```

---

## Seed 3 — `runs/swebench/codex_gpt55_seed_3/`

### Batch V1 — Django part 1 (13 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_3 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "django__django-11790,django__django-11815,django__django-11848,django__django-11880,django__django-11885,django__django-11951,django__django-11964,django__django-11999,django__django-12039,django__django-12050,django__django-12143,django__django-12155,django__django-12193"
```

### Batch V2 — Django part 2 (12 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_3 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "django__django-12209,django__django-12262,django__django-12273,django__django-12276,django__django-12304,django__django-12308,django__django-12325,django__django-12406,django__django-12708,django__django-12713,django__django-12774,django__django-9296"
```

### Batch V3 — Sphinx part 1 (13 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_3 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "sphinx-doc__sphinx-10323,sphinx-doc__sphinx-10435,sphinx-doc__sphinx-10466,sphinx-doc__sphinx-10673,sphinx-doc__sphinx-11510,sphinx-doc__sphinx-7590,sphinx-doc__sphinx-7748,sphinx-doc__sphinx-7757,sphinx-doc__sphinx-7985,sphinx-doc__sphinx-8035,sphinx-doc__sphinx-8056,sphinx-doc__sphinx-8265,sphinx-doc__sphinx-8269"
```

### Batch V4 — Sphinx part 2 (12 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_3 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "sphinx-doc__sphinx-8475,sphinx-doc__sphinx-8548,sphinx-doc__sphinx-8551,sphinx-doc__sphinx-8638,sphinx-doc__sphinx-8721,sphinx-doc__sphinx-9229,sphinx-doc__sphinx-9230,sphinx-doc__sphinx-9281,sphinx-doc__sphinx-9320,sphinx-doc__sphinx-9367,sphinx-doc__sphinx-9461,sphinx-doc__sphinx-9698"
```

### Batch D1 — scikit-learn part 1 (8 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_3 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "scikit-learn__scikit-learn-10427,scikit-learn__scikit-learn-10803,scikit-learn__scikit-learn-11206,scikit-learn__scikit-learn-11596,scikit-learn__scikit-learn-12704,scikit-learn__scikit-learn-13013,scikit-learn__scikit-learn-13283,scikit-learn__scikit-learn-13496"
```

### Batch D2 — scikit-learn part 2 (7 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_3 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "scikit-learn__scikit-learn-13864,scikit-learn__scikit-learn-14125,scikit-learn__scikit-learn-14710,scikit-learn__scikit-learn-15094,scikit-learn__scikit-learn-24677,scikit-learn__scikit-learn-25694,scikit-learn__scikit-learn-3840"
```

### Batch D3 — matplotlib (12 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_3 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "matplotlib__matplotlib-13859,matplotlib__matplotlib-19763,matplotlib__matplotlib-21042,matplotlib__matplotlib-22767,matplotlib__matplotlib-23088,matplotlib__matplotlib-23476,matplotlib__matplotlib-24177,matplotlib__matplotlib-24637,matplotlib__matplotlib-25126,matplotlib__matplotlib-25442,matplotlib__matplotlib-25772,matplotlib__matplotlib-26160"
```

### Batch D4 — xarray + astropy (11 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_3 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "pydata__xarray-2905,pydata__xarray-3520,pydata__xarray-4075,pydata__xarray-4629,pydata__xarray-4911,pydata__xarray-5455,pydata__xarray-6601,pydata__xarray-7003,astropy__astropy-12962,astropy__astropy-13842,astropy__astropy-6938"
```

### Batch D5 — sympy + seaborn (12 problems)

```bash
python -m swebench run \
  --agent-surface codex_cli \
  --codex-model gpt-5.5 \
  --output-dir runs/swebench/codex_gpt55_seed_3 \
  --arms both \
  --parallel 2 \
  --use-cache \
  --filter "sympy__sympy-11232,sympy__sympy-13259,sympy__sympy-14180,sympy__sympy-15976,sympy__sympy-17318,sympy__sympy-19016,sympy__sympy-21596,mwaskom__seaborn-2389,mwaskom__seaborn-2813,mwaskom__seaborn-2946,mwaskom__seaborn-3069,mwaskom__seaborn-3202"
```

### Seed 3 analysis

```bash
python -m swebench analyze summary \
  --results-dir runs/swebench/codex_gpt55_seed_3 \
  --out runs/swebench/codex_gpt55_seed_3/summary.csv
```

---

## Cross-seed analysis

```bash
python -m swebench analyze summary --results-dir runs/swebench/codex_gpt55_seed_1 --out runs/swebench/codex_gpt55_seed_1/summary.csv
python -m swebench analyze summary --results-dir runs/swebench/codex_gpt55_seed_2 --out runs/swebench/codex_gpt55_seed_2/summary.csv
python -m swebench analyze summary --results-dir runs/swebench/codex_gpt55_seed_3 --out runs/swebench/codex_gpt55_seed_3/summary.csv
```

Then aggregate the three CSVs to get mean pass rate ± stderr per arm, and compare against
the equivalent Claude `full_run_seed_N` CSVs for the cross-surface comparison.

## Troubleshooting

**`FileNotFoundError: ~/.codex/auth.json not found`** — auth.json is missing. Re-authenticate
with the Codex CLI interactively before running batches.

**`RuntimeError: exec-server bundle not found`** — run `npm run build` in `exec_server/`.
The bundle path is `exec_server/dist/exec-server.bundle.mjs` relative to the repo root.

**`RuntimeError: node not found on PATH`** — install Node.js or add it to PATH before running.

**`FileNotFoundError: codex binary not found`** — install with `npm install -g @openai/codex`.

**`cost=None` in summary CSV** — the `--codex-model` slug is not in `codex_prices.toml`.
Add a section for the model before running, or accept that cost will be missing for those results.

**Resume not skipping completed instances** — verify both `.jsonl` and `_test.txt` exist for
the triple and that `_test.txt` ends with `PASS` or `FAIL`. Incomplete files (e.g. from a
killed run) are re-run automatically.
