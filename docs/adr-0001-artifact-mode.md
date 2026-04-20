# ADR-0001: Artifact-Graded Benchmark Mode — CLI Surface and Sandbox Wiring

**Status:** STUB — to be filled by epic #92 harness slice (#2).

**Context:** Epic #92 ships a second benchmark mode ("artifact-graded") alongside SWE-bench mode. The on-disk schema for tasks is frozen in [`docs/SCHEMA_ARTIFACT.md`](SCHEMA_ARTIFACT.md). This ADR records the remaining implementation-level decisions that the harness slice must pin before seed tasks land. They are deliberately deferred from the schema doc because they are operational, not structural.

No ADR tooling (e.g. `adr-tools`) exists in this repo today. This single-file pattern is intentional; if the directory grows, migrate to `docs/adr/NNNN-*.md`.

---

## Decision 1 — CLI Surface

*(Epic Open Question #1 — TIMEBOX: harness implementer chooses.)*

Options under consideration:

- **Option A:** A new top-level subcommand, e.g. `python -m swebench artifact run`.
- **Option B:** A mode flag on the existing `run` subcommand, e.g. `python -m swebench run --mode artifact`.

**Decision:** *(to be filled by #2)*

**Rationale:** *(to be filled by #2)*

---

## Decision 2 — Grader Isolation in the `code_only` Arm

*(Epic Open Question #2 — TIMEBOX: harness implementer decides, MUST preserve the no-leak invariant.)*

The `grader/` directory and `reference_output.*` MUST NOT be visible to the agent in any arm (see [`SCHEMA_ARTIFACT.md §5`](SCHEMA_ARTIFACT.md)). For the `code_only` arm in particular, the agent's `execute_code` sandbox needs a PYTHONPATH / working-directory arrangement that cannot accidentally expose the grader via a parent-dir walk or a stray symlink.

Options:

- **Option A:** Copy-on-setup of `workspace/` only into a fresh scratch dir; sandbox cwd is the scratch dir; `grader/` lives outside the scratch dir entirely.
- **Option B:** Materialize the full task dir into scratch then delete `grader/` + `task.yaml` + `reference_output.*`.

**Decision:** *(to be filled by #2)*

**Rationale:** *(to be filled by #2)*

---

## Decision 3 — Cache Layer for `workspace/`

*(Epic Open Question #3 — ESCALATE: decomposer surfaces before harness implementation.)*

The existing OverlayFS cache (`/workspaces/.swebench-cache/`) is structured around git clones and venvs. Artifact-graded tasks have in-repo, local-directory workspaces, which may not need the same caching treatment.

**Decision:** *(to be filled by #2)*

**Rationale:** *(to be filled by #2)*

---

## References

- Epic: [hyang0129/onlycodes#92](https://github.com/hyang0129/onlycodes/issues/92)
- Schema: [`docs/SCHEMA_ARTIFACT.md`](SCHEMA_ARTIFACT.md)
- Child issue (this ADR stub): [hyang0129/onlycodes#93](https://github.com/hyang0129/onlycodes/issues/93)
- Harness child issue: [hyang0129/onlycodes#2 — filed under epic #92]
