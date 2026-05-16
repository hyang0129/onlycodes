# Batched Artifact Run

63 problems split into 7 batches (one category per batch). All batches write to the same output dir so `artifact analyze` sees a single cohesive run at the end.

## How it works

- `--output-dir` is fixed across all batches — results accumulate under `runs/artifact/full_run_seed_1/<instance_id>/<arm>/run<N>/result.json`
- `--resume` (default on) skips any `(task, arm, run)` triple that already has a `result.json` with verdict PASS or FAIL, so re-running a batch or overlapping filters is safe
- `artifact analyze --results-dir runs/artifact/full_run_seed_1` aggregates everything at any point during the campaign

## Commands

```bash
cd /workspaces/hub_1/onlycodes
source .venv/bin/activate
```

### Batch 1 — algorithmic (8 tasks)

```bash
python -m swebench artifact run \
  --output-dir runs/artifact/full_run_seed_1 \
  --filter "algorithmic__bin_packing_first_fit_optimal,algorithmic__coin_change_min,algorithmic__graph_min_vertex_cover,algorithmic__interval_scheduling_weighted,algorithmic__knapsack_01,algorithmic__makespan_scheduling,algorithmic__min_cost_assignment,algorithmic__traveling_salesman_small"
```

### Batch 2 — data_processing (8 tasks)

```bash
python -m swebench artifact run \
  --output-dir runs/artifact/full_run_seed_1 \
  --filter "data_processing__cohort_retention,data_processing__duplicate_orders,data_processing__funnel_conversion,data_processing__multi_file_cohort,data_processing__outlier_days,data_processing__p95_latency_easy,data_processing__regression_detection,data_processing__session_window"
```

### Batch 3 — enumeration (8 tasks)

```bash
python -m swebench artifact run \
  --output-dir runs/artifact/full_run_seed_1 \
  --filter "enumeration__binary_strings_no_run,enumeration__graphs_chromatic_3,enumeration__integer_partitions_15,enumeration__latin_squares_3,enumeration__nqueens_7,enumeration__permutations_fixed_points,enumeration__subset_sum_count,enumeration__sudoku_row_completions"
```

### Batch 4 — iterative_numerical (8 tasks)

```bash
python -m swebench artifact run \
  --output-dir runs/artifact/full_run_seed_1 \
  --filter "iterative_numerical__bisection_calibration,iterative_numerical__exp_decay_fit,iterative_numerical__gauss_newton_circle_fit,iterative_numerical__gradient_descent_rosenbrock,iterative_numerical__hparam_search,iterative_numerical__logistic_fit,iterative_numerical__newton_sqrt,iterative_numerical__secant_root_budgeted"
```

### Batch 5 — stateful_reasoning (8 tasks)

```bash
python -m swebench artifact run \
  --output-dir runs/artifact/full_run_seed_1 \
  --filter "stateful_reasoning__counter_replay,stateful_reasoning__event_ledger,stateful_reasoning__feature_flag_timeline,stateful_reasoning__inventory_reconciliation,stateful_reasoning__rate_limiter_replay,stateful_reasoning__session_fsm,stateful_reasoning__unreachable_functions,stateful_reasoning__upgrade_impact"
```

### Batch 6 — verification_heavy (8 tasks)

```bash
python -m swebench artifact run \
  --output-dir runs/artifact/full_run_seed_1 \
  --filter "verification_heavy__cron_next_fire,verification_heavy__csv_dialect_parser,verification_heavy__expression_evaluator,verification_heavy__iban_validator,verification_heavy__json_pointer_rfc6901,verification_heavy__lru_cache_impl,verification_heavy__parse_iso_duration,verification_heavy__semver_compare"
```

### Batch 7 — data_engineering (15 tasks)

```bash
python -m swebench artifact run \
  --output-dir runs/artifact/full_run_seed_1 \
  --filter "data_engineering__customer_orders_join_easy,data_engineering__dedup_event_log_priority_hard,data_engineering__dedup_inventory_snapshots_medium,data_engineering__dedup_user_profiles_easy,data_engineering__events_cross_region_join_hard,data_engineering__filter_aggregate_sales_easy,data_engineering__filter_aggregate_support_tickets_medium,data_engineering__filter_aggregate_transactions_hard,data_engineering__normalize_audit_log_dedup_hard,data_engineering__normalize_login_timestamps_easy,data_engineering__normalize_order_timestamps_medium,data_engineering__orders_lookup_join_medium,data_engineering__repair_transactions_export_hard,data_engineering__repair_user_directory_medium,data_engineering__transactions_union_medium"
```

## Intermediate analysis

Run at any point — tasks with no results yet simply won't appear:

```bash
python -m swebench artifact analyze --results-dir runs/artifact/full_run_seed_1
```

## Final analysis

Same command once all 7 batches are done:

```bash
python -m swebench artifact analyze \
  --results-dir runs/artifact/full_run_seed_1 \
  --out runs/artifact/full_run_seed_1/summary.csv
```
