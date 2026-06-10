# Gold-gate "fidelity drift": root-cause + fixes (#308)

The image-runtime gold-gate (`scripts/validate_verified_image.py`) applies the
**gold** patch + held-out test patch to the official SWE-bench image and requires
`RESOLVED_FULL`. An instance that does not resolve is excluded from the spine
(`not_resolved`). A full Verified-500 sweep left **8 not_resolved**. This note
records what each one actually was, the two harness bugs it exposed, and what
remains.

## Method

`scripts/diagnose_drift.py` replays the gate per instance and dumps the full
grade (`resolution` + `report` + `status_map`) and raw eval log — the pieces the
result row otherwise drops. For the genuinely-failing ones we then ran the
**exact official `eval_script`** (`make_test_spec(instance).eval_script`, from
the pinned `swebench==4.1.0`) on the same image to separate "our harness
diverges" from "broken upstream too".

## Classification of the original 8

| instance | our gate | exact official eval | cause | disposition |
|---|---|---|---|---|
| django-13089 | not_resolved | ✅ pass | flaky eval | **recovered** (Fix A) |
| django-13344 | not_resolved | ✅ pass | flaky eval | **recovered** (Fix A) |
| matplotlib-20859 | not_resolved | ✅ pass | flaky eval | **recovered** (Fix A) |
| pylint-4661 | ❌ `ModuleNotFoundError: appdirs` | ✅ 51 passed | we skipped the install step | **recovered** (Fix B) |
| astropy-7606 | ❌ 240/241 P2P | ✅ 242 passed | residual gate divergence (1 test) | open — follow-up |
| astropy-8707 | ❌ 148 errors | ❌ 148 errors | nose `setup()` → `PytestRemovedIn8Warning` **raised as error** | env rot — follow-up |
| astropy-8872 | ❌ 0 collected | ❌ 0 collected | distutils `LooseVersion` `DeprecationWarning` → collection error | env rot — follow-up |
| django-10097 | ❌ 5 P2P | ❌ 47 fail / 470 err | DB test-isolation (`no such table: …_old`) | env rot — follow-up |

The warnings-as-errors come from the repos' own `setup.cfg` (`filterwarnings =
error`) combined with the newer pytest/setuptools the images were **rebuilt**
with: a deprecation that was benign when Verified was minted is now fatal during
collection. These fail under the official harness too — i.e. the published images
have drifted, not our reconstruction.

## Two harness bugs this exposed

### Bug 1 — flaky gate frozen by terminal carry-over (Fix A)

`not_resolved` was in `_TERMINAL_STATUSES`, so the resumable sweep **never
retried** it. A single transient eval failure (more likely during the
disk-pressure/prune-thrash era) froze an instance forever. Fix:

- `_gate_one` retries the gate up to `GATE_RETRIES` (3) in a fresh container;
  trust `not_resolved` only after it repeats.
- `--retry-not-resolved` drops prior `not_resolved` rows from the resumed
  terminal set so they get re-gated (recover verdicts recorded before retry
  existed).
- Also fixed a recording bug: the row's `grade` read absent top-level keys
  (`FAIL_TO_PASS`, …) and stored all-null; it now stores the grader's `report`.

Recovered the 3 flakes → **495/500**.

### Bug 2 — unfaithful eval: the install step was skipped (Fix B)

Our `run_eval_in_container` activated the env and ran the test command but
**omitted the official `eval_script`'s install step** (`pip install -e .[test]`).
That step regenerates package metadata and installs declared deps that may be
missing from a published image (pylint's `appdirs`). Fix:
`container_test.reinstall_in_container()` runs the spec's `install` (as **root** —
it writes the root-owned conda `site-packages`) before the eval; threaded through
`gold_patch_gate` / `grade_agent_run` via a new `install_cmd` arg, sourced from
`spec.get("install")` in both the gate (`_gate_one`) and the agent arm
(`run_image_arms` → `run_one_arm`). Failures are non-fatal — the eval surfaces
real breakage.

Recovered pylint-4661 → **496/500**. Applies to **both arms** so gate and agent
grading stay consistent. Cost: one reinstall per eval (~30 s–2 min); accepted for
faithfulness.

## Remaining 4 (follow-up)

- **astropy-7606** — *our bug, still open.* Passes the fully-faithful root eval
  (242 passed) but our gate loses 1 P2P even with the reinstall. Suspected
  root-vs-agent-user or directive-scope/ordering divergence. Tractable.
- **astropy-8707, astropy-8872, django-10097** — *image env rot.* Fail under the
  exact official eval_script too. Recovering them means deviating from the
  published images (pin older pytest/setuptools, or patch the env), which
  compromises faithful reproduction. Candidates for documented exclusion.

## Reproduce

```sh
# diagnose any not_resolved instance (full grade + raw log, images reused)
python scripts/diagnose_drift.py <instance_id> ...
# re-gate prior not_resolved with retry + faithful reinstall
python scripts/validate_verified_image.py --from-file sets/verified-spine.txt \
    --out-dir runs/validation/verified-image-full --retry-not-resolved
```
