# ADR 0005 — Grade SWE-bench Verbatim via Official `run_evaluation`

**Status:** Accepted.
**Date:** 2026-06-11.
**Tracking issue:** [#354](https://github.com/hyang0129/onlycodes/issues/354).
**Builds on:** [ADR-0004](adr-0004-verified-docker-images.md) (image-only runtime).
**Closes by removal:** [#351](https://github.com/hyang0129/onlycodes/issues/351) (Bug A + Bug C), [#353](https://github.com/hyang0129/onlycodes/issues/353) (Bug B). See also [#348](https://github.com/hyang0129/onlycodes/issues/348) (env-rot adjudication).

## Context

ADR-0004 put the benchmark on the official prebuilt images, but the image-runtime
harness still **graded inside a modified eval image**: it stripped `/testbed`'s git
history (anti-cheat), then in the *same* container reinstalled the package, applied
the held-out test patch, ran the eval command, and parsed the log with a hand-rolled
official-parser bridge. Modifying the eval image is the root cause of a cluster of
harness bugs that were never bugs in our logic — they were artifacts of the
strip × reinstall × in-container-eval collision:

| bug | cause (grading inside a modified image) |
|---|---|
| **Bug C** (#351, all 19 pytest) | strip removed version tags → our reinstall mis-versioned (`setuptools_scm` resolved `0.1.dev1`) → pytest `minversion` self-rejected the whole run |
| **Bug A** (#351, `assert_no_leak` over-match) | the held-out test was applied in the *same* container the agent had touched, forcing an aggressive in-container leak scan that false-positived |
| **Bug B** (#353, official-venv TOCTOU) | a hand-rolled grader subprocess raced its own pinned venv build |

Each "fix" was a patch on a structure that should not exist. The agent workspace
(our contribution — vary `code_only` vs `tool_rich`) and the grading environment
(SWE-bench, fixed) are two concerns the old design fused into one container.

## Decision

**Decouple the agent workspace from grading; grade verbatim.** The harness and the
environment become separate concerns joined only by a file:

- **Concern A — agent workspace.** Pull → *disposable*, history-stripped container →
  stage the tool surface → run the agent → capture the agent's diff
  (`container_agent.extract_agent_diff` → `model_patch`). Anti-cheat (the strip) lives
  here and only here.
- **Concern B — grading / env.** Take `predictions.jsonl`
  (`{instance_id, model_name_or_path, model_patch}`) and grade **byte-for-byte**
  through official `python -m swebench.harness.run_evaluation` on the **unmodified**
  prebuilt image (`grading_official.grade_predictions`), reading `report.json` back.
  We never touch an eval image.

**The seam is `predictions.jsonl` → `report.json`.** Concern A does not know how
grading works; Concern B does not know how the patch was produced. The image runtime
becomes a two-pass flow: agent pass (emit `PENDING` records + the patch) → grading pass
(`grade_predictions` per arm, parallel via `max_workers`, merge verdicts).

The #354 spike proved the seam: a pytest-5262 gold patch through `run_evaluation`
returned `resolved: true`, reusing our cached image with no re-pull.

## Consequences

- **The three bugs close by removal, not by patch.** With the image unmodified and
  the held-out test applied only in the separate grading container, Bug C cannot
  occur (history intact), Bug A has nothing to scan (no shared container), and Bug B
  is gone (`run_evaluation` is the grader; its venv is built once, eagerly,
  concurrency-safe). #351 and #353 are won't-fix — cause removed.
- **~565 LoC of custom grading deleted.** `swebench/container_test.py` (gold gate,
  in-container eval, faithful reinstall, eval directives), `swebench/official_grade.py`
  (in-container-log grader), `scripts/_official_grade_runner.py` (its subprocess
  entry), and `container_agent`'s `assert_no_leak` / `held_out_markers_from_patch` /
  `ContainerLeakError` / `_LEAK_FIND_SCRIPT`, plus their tests.
- **We follow SWE-bench byte-for-byte.** Grading parity is definitional, not
  approximated — our resolution status *is* the official one.
- **We lose nothing.** The image is the faithful frozen artifact (ADR-0004); grading
  on it verbatim is strictly more faithful than re-deriving the eval in a mutated copy.
- **Environment rot is adjudicated upstream.** Instances that fail under the official
  harness (#348) are genuine upstream breakage to document/exclude; instances that
  passed there but failed for us were our-modification artifacts, recovered for free.
- **Cost/turns accounting is unchanged** — they still come from the agent transcript,
  produced in the agent pass.

## References

- [#354](https://github.com/hyang0129/onlycodes/issues/354) — verbatim-grading transition (this ADR).
- [#351](https://github.com/hyang0129/onlycodes/issues/351) — Bug A (leak over-match) + Bug C (19-pytest setuptools_scm), closed by removal.
- [#353](https://github.com/hyang0129/onlycodes/issues/353) — Bug B (official-venv TOCTOU), closed by removal.
- [#348](https://github.com/hyang0129/onlycodes/issues/348) — env-rot instances, re-adjudicated against the official harness.
- [ADR-0004](adr-0004-verified-docker-images.md) — image-only runtime this builds on.
- `docs/VERBATIM_GRADING_PLAN.md` — the phased transition plan.
