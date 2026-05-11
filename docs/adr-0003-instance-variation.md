# ADR 0003 — Per-Instance Workspace Generators for `algorithmic` and `verification_heavy`

**Status:** Accepted.
**Date:** 2026-05-10.
**Tracking issue:** [#172](https://github.com/hyang0129/onlycodes/issues/172).

## Context

`docs/SCHEMA_ARTIFACT.md` §5.1 defines `workspace_generator` as the
mechanism for materialising bulk task inputs deterministically from
`sha256(instance_id)`. The data-processing and stateful-reasoning
categories already use generators; the other four (`algorithmic`,
`verification_heavy`, `enumeration`, `iterative_numerical`) do not.

Concretely, the seed-v1 corpus today looks like this:

| Category              | Workspace shape                              | Per-instance variation? |
|-----------------------|----------------------------------------------|-------------------------|
| `algorithmic`         | static `parcels.json` / `graph.json` / ...   | NO                      |
| `verification_heavy`  | empty workspace; agent writes `solution.py`  | NO                      |
| `enumeration`         | mostly inputless / static                    | NO                      |
| `iterative_numerical` | mixed; some have `black_box.py` source       | partial                 |
| `data_processing`     | `workspace_generator`, sha256-seeded         | YES                     |
| `stateful_reasoning`  | `workspace_generator`, sha256-seeded         | YES                     |

This inconsistency is load-bearing in a way that matters: the static
categories are gameable by any model whose training corpus has seen the
benchmark. The schema introduces `workspace_generator` *specifically* to
mitigate memorisation; the mitigation is half-applied.

Two ways to stop being inconsistent:

- **(a)** Add `workspace_generator` to `algorithmic` and
  `verification_heavy` (this ADR).
- **(b)** Accept that those categories are "single-instance probes",
  document the limitation, and tag them.

## Decision

**(a)** Add `workspace_generator` scripts to all eight `algorithmic`
tasks and all eight `verification_heavy` tasks, matching the conventions
already established for `data_processing`.

## Why generators (not single-instance probes)

- **Memorisation resistance.** A model that has seen the seed-v1 inputs
  for `knapsack_01` can memorise the optimum (`total_value: 550` was a
  static, committed value). A model that has only seen the
  problem-shape, not a specific instance, must actually solve the
  problem. The headline numbers we publish should measure the latter.

- **Cheap to grow the corpus.** With a generator, adding a second
  instance (`knapsack_02`, `knapsack_03`, …) is a single-line change to
  the slug. With static inputs, every new instance is hand-authored.

- **Reference output stays well-defined.** For algorithmic, the grader
  already recomputes the optimum from the input — adding a generator
  required zero grader changes. For verification_heavy, the grader's
  property tests are hidden and already seed from `instance_id`
  (SCHEMA §3.2.3); the workspace generator produces sample inputs the
  agent can use as development scratch.

- **Consistency with the existing schema.** SCHEMA §5.1 already
  specifies the generator contract (stdlib-only, scrubbed env, sha256
  seed, marker-file idempotency). This ADR does not invent new
  machinery; it applies existing machinery to the remaining
  categories.

## Implementation

For each of the 16 affected tasks:

1. **`workspace/generator.py`** — stdlib-only Python script taking
   `--seed`, `--output-dir`, `--instance-id`. Produces the input file
   the task expects (`parcels.json` for knapsack, `graph.json` for
   vertex cover, `examples.json` for verification_heavy, …). All
   randomness flows from the seed.

2. **`task.yaml`** — declares `workspace_generator: workspace/generator.py`.
   No other field changes.

3. **`grader/reference_output.json`** (algorithmic only) — regenerated
   from the canonical seed for the task's `instance_id`
   (`int(sha256(instance_id)[:8], 16)`). The grader continues to read
   the workspace and compute the optimum itself — the reference file
   is for the pre-merge sanity check (SCHEMA §5.4) only.

4. **Static workspace inputs removed.** The previously committed
   `parcels.json`, `graph.json`, `cost_matrix.json`, etc., are deleted.
   The generator is now the sole source of bulk data. (`workspace/verify.py`
   is unchanged — it is hand-curated and small.)

5. **`tools/regen_reference_outputs.py`** — committed CLI that
   regenerates every algorithmic `reference_output.json` from its
   canonical seed in one pass. Use this after any generator edit that
   would invalidate the reference.

### Per-category notes

**Algorithmic (8 tasks).** Workspaces previously contained a single
static JSON input. The generator writes the same filename
deterministically from the seed. The grader is unchanged and was
already optimum-recomputing.

**Verification heavy (8 tasks).** Workspaces previously contained only
`verify.py`. The generator adds `examples.json` — a small seeded
sample set the agent can replay against their solution during
development. This is purely a development aid; the hidden grader's
property tests are independent. `grader/reference_output.py`
(the canonical solution) is unchanged because it works against any
seeded input.

## Consequences

- **Pre-merge sanity check (SCHEMA §5.4).** Continues to work
  unchanged: the harness materialises the workspace via the canonical
  seed, drops `grader/reference_output.json` at the output path, and
  asks the grader to grade it. Both sides see the same seeded inputs.

- **Negative sanity check (SCHEMA §5.5).** Continues to work
  unchanged: the default mutations operate on the reference output
  text, independent of the workspace contents.

- **`grader/hidden.py` invariants (SCHEMA §3.2).** No grader changed
  in this ADR. Determinism, no-network, sha256-seeded randomness,
  cheap, no-clock-dependence are all preserved.

- **Materialisation cost.** Each generator runs in well under a
  second on the listed input sizes (15-50 items, 18-node graphs,
  20×20 matrices, 12-point TSP).

- **Backwards compatibility.** The harness already supports
  `workspace_generator`. Tasks without the field continue to work
  via the existing copy-only materialisation path.

## Acceptance criteria (from #172)

- [x] Decision recorded in this ADR.
- [x] Generators follow `data_processing` conventions: stdlib-only,
      derive seed from `sha256(instance_id)`, support
      `--seed/--output-dir/--instance-id` CLI.
- [x] Reference-output regeneration script committed
      (`tools/regen_reference_outputs.py`).
- [x] All 16 algorithmic + verification_heavy tasks have a
      `workspace_generator`.
- [x] No new tags introduced; `single_instance` is unused.

## Reversibility

Going back to static inputs is a `git revert` of this PR. Static
`parcels.json` etc. would be restored to their previous bytes; the
generator scripts would be removed; `task.yaml` would drop the
`workspace_generator` field. Reference outputs are regenerated
deterministically either way, so no manual repair is needed on a
revert.
