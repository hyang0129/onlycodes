# ADR-0001: Artifact-Graded Benchmark Mode — CLI Surface and Sandbox Wiring

**Status:** Accepted (filled by harness slice #94).

**Context:** Epic #92 ships a second benchmark mode ("artifact-graded") alongside SWE-bench mode. The on-disk schema for tasks is frozen in [`docs/SCHEMA_ARTIFACT.md`](SCHEMA_ARTIFACT.md). This ADR records the remaining implementation-level decisions that the harness slice must pin before seed tasks land. They are deliberately deferred from the schema doc because they are operational, not structural.

No ADR tooling (e.g. `adr-tools`) exists in this repo today. This single-file pattern is intentional; if the directory grows, migrate to `docs/adr/NNNN-*.md`.

---

## Decision 1 — CLI Surface

*(Epic Open Question #1 — TIMEBOX: harness implementer chooses.)*

Options under consideration:

- **Option A:** A new top-level subcommand, e.g. `python -m swebench artifact run`.
- **Option B:** A mode flag on the existing `run` subcommand, e.g. `python -m swebench run --mode artifact`.

**Decision:** Option A. A new `artifact` Click group wired into `swebench/cli.py`
with subcommands `run` (full) and `verify` (placeholder for #96).

**Rationale:** Additive-only preserves byte-identical behaviour of the existing
`python -m swebench run` command (a hard slice invariant). The two modes have
disjoint primitives — artifact mode uses `Task` / `GradeResult`, SWE-bench mode
uses `Problem` / test patches — so sharing a single `run` entrypoint would
require option-gated branching that is hard to reason about. The two groups
share infrastructure (`harness.run_claude`, `find_claude_binary`) by import,
not by flag plumbing.

---

## Decision 2 — Grader Isolation in the `code_only` Arm

*(Epic Open Question #2 — TIMEBOX: harness implementer decides, MUST preserve the no-leak invariant.)*

The `grader/` directory and `reference_output.*` MUST NOT be visible to the agent in any arm (see [`SCHEMA_ARTIFACT.md §5`](SCHEMA_ARTIFACT.md)). For the `code_only` arm in particular, the agent's `execute_code` sandbox needs a PYTHONPATH / working-directory arrangement that cannot accidentally expose the grader via a parent-dir walk or a stray symlink.

Options:

- **Option A:** Copy-on-setup of `workspace/` only into a fresh scratch dir; sandbox cwd is the scratch dir; `grader/` lives outside the scratch dir entirely.
- **Option B:** Materialize the full task dir into scratch then delete `grader/` + `task.yaml` + `reference_output.*`.

**Decision:** Option A. The harness calls `shutil.copytree(task_dir /
"workspace", scratch_dir)` and never references `task_dir / "grader"` during
materialization. The agent subprocess is launched with `cwd=scratch_dir` and
no PYTHONPATH injection of the repo root. `swebench.artifact_materialize`
enforces the invariant with a post-copy scan that fails loudly if any file
named `hidden.py` or `reference_output*` is present in the scratch tree.

**Rationale:** Copy-then-delete (Option B) is strictly more error-prone — a
bug in the deletion step silently leaks the golden answer into the agent
sandbox. Copy-only means the leak invariant is a property of the code that
was never written, not of a post-hoc scrub step. The runtime scan exists
only as a tripwire for future misconfiguration (e.g. a task author
accidentally putting `reference_output` inside `workspace/`).

---

## Decision 3 — Cache Layer for `workspace/`

*(Epic Open Question #3 — ESCALATE: decomposer surfaces before harness implementation.)*

The existing OverlayFS cache (`/workspaces/.swebench-cache/`) is structured around git clones and venvs. Artifact-graded tasks have in-repo, local-directory workspaces, which may not need the same caching treatment.

**Decision:** Artifact mode does NOT use the OverlayFS cache. No artifact-mode
module imports `swebench.cache`. Each run creates a fresh scratch dir with
`shutil.copytree`; the previous run's scratch is left intact on disk (supports
`--resume` and post-run inspection).

**Rationale:** The cache pays for itself only when setup is expensive (cloning
a large repo, building a venv). Artifact workspaces are self-contained trees
of hand-curated input files — typically kilobytes, always sub-50MB per the
schema's cap. Copying them per-run costs less than the overlay mount/unmount
cycle. Skipping the cache also removes an entire class of bugs (leaked pip
installs, stale lockfiles, fuse-overlayfs fallbacks) from the artifact-mode
critical path.

---

## References

- Epic: [hyang0129/onlycodes#92](https://github.com/hyang0129/onlycodes/issues/92)
- Schema: [`docs/SCHEMA_ARTIFACT.md`](SCHEMA_ARTIFACT.md)
- Child issue (this ADR stub): [hyang0129/onlycodes#93](https://github.com/hyang0129/onlycodes/issues/93)
- Harness child issue: [hyang0129/onlycodes#2 — filed under epic #92]
