# SWE-bench Mini — Batched Run Results (verified-mini, partial)

Status as of 2026-05-10. Companion to [BATCHED_RUN_SWE.md](BATCHED_RUN_SWE.md).

## Scope

- **Run dir:** `runs/swebench/full_run_seed_1/`
- **Completed:** 50/100 instances — the full `swebench-verified-mini` set (Django 25, Sphinx 25, batches V1–V4).
- **Not yet run:** `swebench-datasci-mini` (50 instances, batches D1–D5: scikit-learn, matplotlib, xarray, sympy, seaborn, astropy).
- **Arms:** `baseline` (full tool suite), `onlycode` (execute_code MCP only), `bash_only` (Bash-only built-ins). 1 run per (instance, arm).

## Headline numbers

| Arm | PASS | Rate | Total cost | Total turns |
|---|---|---|---|---|
| baseline  | 32/50 | 64.0% | $26.46 | 1,098 |
| onlycode  | 34/50 | **68.0%** | $28.17 | 1,688 |
| bash_only | 32/50 | 64.0% | $44.51 | 1,731 |

- onlycode is +2 instances over baseline (+4pp) — within noise at n=50, but never worse on aggregate.
- bash_only matches baseline pass rate but spends ~1.7× the dollars and ~58% more turns.
- Per-turn cost: baseline ≈ $0.024, onlycode ≈ $0.017, bash_only ≈ $0.026. onlycode's turns are the cheapest, consistent with short REPL ops vs. shell spinups.

## By repo

| Repo | baseline | onlycode | bash_only |
|---|---|---|---|
| django (25)     | 22 (88%) | 23 (92%) | 23 (92%) |
| sphinx-doc (25) | 10 (40%) | 11 (44%) |  9 (36%) |

Django is largely saturated across arms. Sphinx is where the hard tail lives and where arm differences would show up — but the n=25 sub-sample is too small to call.

## Agreement across arms (n=50)

| baseline | onlycode | bash_only | count |
|---|---|---|---|
| PASS | PASS | PASS | 30 |
| FAIL | FAIL | FAIL | 14 |
| FAIL | **PASS** | FAIL |  3 |
| FAIL | **PASS** | **PASS** |  1 |
| **PASS** | FAIL | FAIL |  1 |
| **PASS** | FAIL | **PASS** |  1 |

- 44/50 instances are unanimous (30 pass, 14 fail) — most of the suite doesn't discriminate between arms.
- onlycode-unique wins: 3 (instances where only onlycode passed).
- onlycode-unique losses: 1.
- The signal lives in 6 instances. With this much noise, the +2 onlycode lead is suggestive, not conclusive.

## Caveats

- **Half the suite is missing.** Datasci-mini (sklearn, matplotlib, xarray, sympy, seaborn, astropy) has not been run. Numerical/scientific code may stress arms differently than web-framework code.
- **Single run per arm.** No variance estimate. The 6 split instances dominate the headline delta — re-running them would tell us if those splits are stable.
- **Sphinx sub-sample is small.** That's where arm differences are most likely to materialize, and we have only 25 instances.

## Next steps

1. Run D1–D5 to fill out the datasci half.
2. Once complete, regenerate the summary CSV: `python -m swebench analyze summary --results-dir runs/swebench/full_run_seed_1 --out runs/swebench/full_run_seed_1/summary.csv`.
   - **Known gap:** `analyze summary` currently only emits `baseline`/`onlycode` rows; `bash_only` is omitted from the CSV. Aggregate bash_only stats in this doc were computed by parsing `*_bash_only_run1_test.txt` and the matching JSONL `result` events directly. Worth fixing in the analyzer before the final write-up.
3. Consider re-running the 6 split instances to estimate variance before reporting a verdict.
