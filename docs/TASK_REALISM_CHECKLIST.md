# Task Realism Checklist (v1)

Self-applied by the author of every artifact-graded task in `problems/artifact/`. Created per issue #128.

**Purpose.** The onlycodes benchmark contrasts a tool-restricted Claude arm against a tool-rich one on work a practitioner would actually recognize. Tasks engineered to stress or favor a particular arm are explicitly out of scope. A task is "realistic" when it looks like something a working data engineer, ML engineer, or research programmer would receive as a ticket, memo, or DM — not a textbook exercise.

## How to use this document

When authoring a new task:

1. Work through every checkbox below. Each one is binary — if you cannot answer "yes" outright, the item is a "no".
2. Fix any "no" item before opening a PR. If you cannot fix it (e.g. the problem genuinely needs a banned library), either reshape the task or drop it.
3. Record compliance in `task.yaml` by adding the tag `realism_checklist_v1` to the `tags:` list. This tag is the on-disk evidence that the author self-certified against this checklist. See `swebench/artifact_loader.py` — the loader does not enforce the tag, but CI/review tooling may.
4. Keep this document versioned. If the criteria change materially, bump the version (`realism_checklist_v2`) rather than mutating v1 in place.

## v1 criteria

### Libraries

- [ ] The agent-facing code paths (the problem as stated, any hints, and any `structural_verifier`) use only: `pandas`, `numpy`, `scikit-learn`, `scipy`, or the Python standard library.
- [ ] The `workspace_generator.py` script (if present) imports from the Python standard library only. **No pandas, no numpy, no sklearn, no scipy in generators** — the materialize env is deliberately scrubbed (see SCHEMA §5.1).
- [ ] No `matplotlib`, `seaborn`, `plotly`, `bokeh`, `altair`, or any other visualization library is imported anywhere under the task directory.
- [ ] No `networkx`, `polars`, `dask`, `pyarrow`-standalone, `duckdb`, `torch`, `tensorflow`, `jax`, `xgboost`, `lightgbm`, or similar heavyweight libraries.
- [ ] No `requests`, `urllib`, `httpx`, `socket`, or any other network I/O — tasks run fully offline.
- [ ] No GPU-dependent code paths.

### Problem framing

- [ ] The `prompt.md` reads like a ticket, memo, Slack message, or email a working practitioner would plausibly receive. It states the business question, not a math problem.
- [ ] Variable names, column names, and file names match domain conventions a practitioner would use (e.g. `order_id`, `event_ts`, `churn_label`, `p95_latency_ms`). No `foo`, `bar`, `x`, `y` in the problem-facing surface.
- [ ] The success criterion is something a practitioner would actually care about — a correct number, a correct prediction, a correct aggregate, a correct transform — not trivia.

### Data shape

- [ ] If the task includes tabular data, the schema is non-trivial (multi-column DataFrame, multi-file layout, mixed dtypes, or realistic skew).
- [ ] If the task includes array data, the shape resembles real measurements (time series, image-like grid, feature matrix), not a toy vector.
- [ ] Input data volume is bounded: total workspace size ≤ 50 MB, row count ≤ 1M per file. (SCHEMA §8.)
- [ ] Individual files ≤ 10 MB. (SCHEMA §8.)

### Execution envelope

- [ ] A competent practitioner could complete the task in ≤ 30 minutes of wall time on the harness venv. (Reference solution should typically run in seconds.)
- [ ] The task does not require more than 50 `execute_code` invocations on the happy path. (Declared as `max_code_runs: 0` / unlimited per SCHEMA §2.3 — enforcement is off — but design within this envelope anyway.)

### Grader

- [ ] `grader/hidden.py:grade()` is deterministic. Given the same `scratch_dir`, it always returns the same `GradeResult`.
- [ ] The grader is offline — no network, no external files outside `scratch_dir` and the task's own `grader/` directory.
- [ ] The grader does not write to `scratch_dir`.
- [ ] The grader's pass/fail decision checks behavior a practitioner would actually care about, not trivia (e.g. field presence, numeric tolerance, ordering invariants — not exact float equality where floating-point drift is expected).
- [ ] The grader handles malformed-output cases gracefully (missing file, bad JSON, wrong shape) and returns `passed=False` with a useful `detail` — it does not crash the harness.
- [ ] `reference_output.*` is a known-good artifact that grades `passed=True, score=1.0`. (Enforced by `tests/test_verify_graders.py`.)

### Arm neutrality

- [ ] The task does NOT require reading many files via filesystem tools (would favor the tool-rich arm).
- [ ] The task does NOT require many small code-execution steps (would favor the code-only arm).
- [ ] The task is solvable by either arm with only a modest efficiency difference attributable to tool availability, not task design.
- [ ] The problem statement makes no reference to specific tools the agent should or should not use.

### No-leak invariant

- [ ] `grader/hidden.py` is **not** placed under `workspace/` — it lives only in `grader/` and is never copied into the agent's scratch dir.
- [ ] `reference_output.*` is **not** placed under `workspace/` — it lives only in `grader/`.
- [ ] If a `workspace_generator.py` is used, it is placed under `workspace/` (so the harness can exclude it from the scratch copy) — not under `grader/`.

### Difficulty ladder

- [ ] The author has placed this task on the `easy` / `medium` / `hard` ladder per an honest assessment of the effort a practitioner would spend. Rule of thumb:
  - **easy** — a practitioner solves it in ≤ 5 minutes of focused work, mostly straight-line code.
  - **medium** — 5–15 minutes, involves at least one decision (algorithm choice, library function selection, correctness check).
  - **hard** — 15–30 minutes, involves multi-step reasoning, non-obvious edge cases, or composing several capabilities.

### Category fit

- [ ] The task's primary work matches its declared `category`:
  - `data_processing` — pandas / numpy / tabular ingestion, transformation, aggregation.
  - `algorithmic` — combinatorial optimization, graph work, scheduling.
  - `verification_heavy` — correctness-critical parsing, stateful machines, subtle invariants.
  - `enumeration` — exhaustive search under a constraint.
  - `stateful_reasoning` — event streams, sequential state, replay.
  - `iterative_numerical` — root-finding, fitting, optimization, hyperparameter search.

## Compliance marker

When every box above is checked, add `realism_checklist_v1` to `task.yaml:tags`:

```yaml
tags:
  - <existing tags...>
  - realism_checklist_v1
```

This marker is versioned — if the criteria here change materially, bump to `realism_checklist_v2` so older tasks are clearly still certified against v1.
