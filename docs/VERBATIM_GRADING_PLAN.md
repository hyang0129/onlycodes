# Transition plan: verbatim SWE-bench grading (#354)

**Principle.** Two concerns that the current image-runtime harness merges become
cleanly separate:

- **Concern A — Agent harness (the workspace).** Pull image → *disposable*
  container → strip history (anti-cheat) → stage tool surface → run agent →
  **capture the agent's diff (`model_patch`) + transcript metrics**. Owns:
  `image_store`, `container.{prepare,start,teardown}`, `container_agent`
  (`stage_arm`, `run_agent`, `extract_agent_diff`, strip), `runner` tool
  surfaces. This is **our contribution** — vary it (code_only vs tool_rich).

- **Concern B — Grading / env (the benchmark).** Take `predictions.jsonl`
  (`{instance_id, model_name_or_path, model_patch}`) and grade **verbatim**
  through official `python -m swebench.harness.run_evaluation` on the
  **unmodified** prebuilt image. Owns: one thin adapter + the official swebench
  venv. **We never touch the eval image.** This is SWE-bench, byte-for-byte.

**The seam between them is a file:** `predictions.jsonl` in, `report.json` out.
Nothing in Concern A knows how grading works; nothing in Concern B knows how the
patch was produced. Spike (#354) proved the seam: pytest-5262 gold patch →
`run_evaluation` → `resolved: true`, 108/108, reusing our cached image, no
re-pull.

---

## Why this removes bugs instead of patching them

All three open harness bugs are artifacts of grading inside a modified eval
image. Verbatim grading removes the cause:

| bug | cause (current) | under verbatim |
|---|---|---|
| Bug C (#351, all 19 pytest) | strip removes tags → our reinstall mis-versions (setuptools_scm `0.1.dev1`) → pytest `minversion` self-reject | image unmodified, history intact → cannot occur |
| Bug A (#351, `assert_no_leak` over-match) | held-out test applied in the *same* container the agent touched → aggressive in-container scan | test patch applied only in the separate grading container → nothing to scan |
| Bug B (#353, official-venv TOCTOU) | hand-rolled grader subprocess racing its venv | `run_evaluation` is the grader; venv built once, eagerly (see Phase 1) |

---

## Target architecture

```
PHASE 1 — agent (Concern A), per (instance × arm × run), resumable per unit
  image_store.ensure_image
  container.prepare_instance(+strip, +agent_user)         # disposable
  container_agent.stage_arm / run_agent                   # code_only | tool_rich
  model_patch = container_agent.extract_agent_diff(...)   # <-- the only output that escapes
  container.teardown
  -> write partial record: {meta, transcript, model_patch, cost, turns, verdict: "PENDING"}

PHASE 2 — grade (Concern B), per (arm × run), batched across instances
  predictions.jsonl  = [{instance_id, model_name_or_path: arm, model_patch} ...]
  grading_official.grade_predictions(preds, run_id=<run>_<arm>, max_workers=N)
    -> subprocess: python -m swebench.harness.run_evaluation (official venv, non-shadowing cwd)
    -> read report.json  {instance_id: {resolved, tests_status, ...}}
  merge verdict back into each record
```

Phase 1 = "harness." Phase 2 = "env/grading." They no longer share a container.

---

## New / changed / deleted

### New
- **`swebench/grading_official.py`** (or repurpose `official_grade.py`): the
  Concern-B adapter.
  - `ensure_official_venv()` — moved here; **built eagerly once** at run start and
    made concurrency-safe (atomic build via tmp+rename / import-readiness check) —
    **this is the #353 fix**.
  - `grade_predictions(predictions, *, run_id, dataset="princeton-nlp/SWE-bench_Verified", namespace="swebench", instance_ids=None, max_workers=1, cache_level="instance") -> dict[iid, dict]`
    — writes a temp predictions.jsonl, invokes `run_evaluation` in the official
    venv from a non-shadowing cwd (`/tmp`, so the local `swebench/` package can't
    shadow the installed `swebench==4.1.0`), parses `report.json` + the per-instance
    grade json, returns `{iid: {resolved, tests_status}}`.
  - `grade_one(instance_id, model_patch, **kw)` — convenience single-instance wrapper
    (smoke / validation / drift triage).

### Changed
- **`swebench/image_run.py`**
  - `run_one_arm`: drop the `grade_agent_run` call + `install_cmd` arg; after
    `run_agent`, call `extract_agent_diff` → store `model_patch`; record verdict
    `PENDING`.
  - `run_image_arms`: split into Phase 1 (agent loop, emits partial records +
    in-memory/on-disk predictions) and Phase 2 (per-arm `grade_predictions`,
    merge verdicts). Add `--parallel` to the grading pass (`max_workers`).
  - `_grading_instance`/`_read_test_patch`: no longer needed for grading (the
    official dataset supplies test_patch/F2P/P2P). Keep only if still used for
    record metadata; otherwise delete.
- **`swebench/run.py`** `_run_image_runtime`: thread the grading `max_workers`
  and `run_id`; otherwise unchanged dispatch.
- **`swebench/container_agent.py`**: keep `extract_agent_diff` (now load-bearing),
  `agent_user_setup_commands`, strip, `stage_arm`, `run_agent`. Replace the heavy
  `assert_no_leak` container scan with a light **diff-only** check (does the
  agent's `model_patch` touch files the held-out test patch will apply?) — optional
  guard, logged, non-fatal. (Closes Bug A by deletion of the scan.)

### Deleted (image path only — overlay grading in `harness.py` is separate, #341)
- `swebench/container_test.py`: `gold_patch_gate`, `grade_agent_run`,
  `run_eval_in_container`, `reinstall_in_container`, and `install_cmd` plumbing.
  Keep `apply_patch_in_container` only if still used by a validation helper;
  `eval_directives`/`build_eval_command` likely go.
- `swebench/official_grade.py`: `grade()` (in-container-log grading) and
  `is_resolved()` for that path — replaced by reading `run_evaluation`'s report.
  `_official_grade_runner.py` → deleted (run_evaluation is the runner).
- Tier-0 / gold-gate scripts collapse (see Phase 4).

---

## Phased sequence (each phase shippable + reversible)

### Phase 0 — Spike ✅ (done, #354)
pytest-5262 gold → verbatim `run_evaluation` → resolved, cached image reused.

### Phase 1 — Grading adapter (`grading_official.py`)
Build `ensure_official_venv` (eager, concurrency-safe) + `grade_predictions` +
`grade_one`. Unit-test against a known gold patch (resolved) and an empty patch
(unresolved/empty). **Folds in #353.** No orchestration change yet.
*Acceptance:* `grade_one("pytest-dev__pytest-5262", gold)` → resolved; empty → not.

### Phase 2 — Agent arm emits `model_patch`
`run_one_arm`: after `run_agent`, `extract_agent_diff` → record. Verdict
`PENDING`. Stop calling `grade_agent_run`. Records now carry the patch.
*Acceptance:* a stub-agent run produces a record with a non-empty `model_patch`
and no grading side-effects.

### Phase 3 — Two-pass orchestration
`run_image_arms` = agent pass (Phase 1 records) → grading pass
(`grade_predictions` per arm, `max_workers`) → merge verdicts. Decouples the two
concerns end-to-end.
*Acceptance:* gold-as-agent over a 1-per-repo sample → all resolved through the
two-pass path (incl. all repos that Bug C broke).

### Phase 4 — Collapse validation tooling
- `scripts/validate_verified_image.py` → **gold-predictions over the set**
  through `run_evaluation`; "buildable" = officially resolved. Re-adjudicate the
  env-rot handful (#348) against the official harness: fail-there ⇒ genuine
  upstream breakage (document/exclude); pass-there ⇒ our-modification artifact,
  recovered for free.
- `scripts/verify_agent_grade.py` (Tier 0 brackets): gold preds → all resolved;
  empty preds → `run_evaluation`'s own `empty_patch_instances`. Simplify or retire.
- `scripts/diagnose_drift.py` → thin `grade_one` + dump official log. Likely retire.

### Phase 5 — Delete dead code + update tests/docs
Remove the deleted functions and their tests; rewrite `test_image_run`,
`test_container_test` (image-grading parts), `test_official_grade`,
`test_validate_verified_image`. Update **CLAUDE.md** invariants (drop "faithful
reinstall", "install_cmd", in-container grading; add the two-concern model +
predictions seam) and add an **ADR** ("grade verbatim; agent workspace
decoupled"). Close #351 (Bug A/C) and #353 (Bug B) as won't-fix — removed cause.

### Phase 6 — Prove e2e
Re-run Tier 0 (gold-as-agent) over the full buildable set through the verbatim
path → expect ~496/496 (the 19 pytest now pass). Then a codex baseline smoke
(1-per-repo) as the first real verbatim arm.

---

## Key decisions & risks

1. **Batch per arm (chosen) vs per-instance grading.** `run_evaluation` keys by
   `instance_id`, so two arms can't share one predictions file/run. Grade **one
   `run_evaluation` per (arm, run)** over all instances, `max_workers=N` —
   efficient, parallel across instances, clean resume (run_evaluation logs per
   instance under its `run_id`). `grade_one` remains for smoke/validation.
2. **Dataset source.** Use the canonical HF dataset
   (`princeton-nlp/SWE-bench_Verified`) so test_patch/F2P/P2P never drift from
   official. Network + HF token required at grade time (already used); cache it.
   *(Local-json dataset is a fallback if offline grading is ever needed.)*
3. **Image reuse.** `--namespace swebench --cache_level instance` reused our
   cached images and removed 0 (spike). Keep `image_store` for pre-pull +
   reuse-forever; `run_evaluation` consumes them. No extra pulls, no rate-limit
   pressure.
4. **Anti-cheat preserved.** Strip stays in the *agent* container (disposable).
   The agent never shares a container with the held-out test, so the leak vector
   is gone; keep only a light diff-level guard.
5. **Overlay path untouched.** It grades via `harness.py` (`apply_test_patch` +
   `run_tests`), independent of the image grading we're deleting, and is already
   deprecated (#341). Don't entangle the two; this transition may *precede* the
   #341 removal.
6. **Cost accounting unchanged.** cost/turns still come from the agent transcript
   (`_extract_cost_turns`), produced in Phase 1.

---

## Acceptance for #354 (whole transition)

- [ ] Grading is `run_evaluation`-only; no onlycodes code modifies an eval image.
- [ ] Agent arm emits valid `predictions.jsonl` from `extract_agent_diff`.
- [ ] Two-pass orchestration; grading parallel via `max_workers`.
- [ ] Custom image-grading path deleted; #351 + #353 closed as removed-cause.
- [ ] Env-rot instances adjudicated against the official harness.
- [ ] Full Tier 0 (gold-as-agent) verbatim → ~496/496; codex smoke clean.
- [ ] CLAUDE.md + ADR updated to the two-concern model.
