# Env-Fix Loop for SWE-bench

Playbook for hunting and resolving environment-level failures in a SWE-bench problem
set in a single PR. Used to land [PR #263](https://github.com/hyang0129/onlycodes/pull/263),
which closed 5 issues (#258–#262) covering 16/25 broken sphinx instances in
`swebench-verified-mini`.

The shape: **parallel baseline sweep → triage verdicts → batch-fix in one PR →
iterate diagnose/fix/rerun until clean.**

---

## When to use this loop

After any of:
- A new problem set is added (e.g. fresh HuggingFace fetch into `problems/swe/`).
- Major harness / dependency churn (pytest/setuptools/numpy bumps).
- Periodic env-drift audit on an existing set.
- Suspicion that pass rates are deflated by hidden env failures rather than agent skill.

Not for: per-instance one-off fixes (just open a single issue + PR), or for FAIL
verdicts that look like genuine agent misses (assertion errors against the new
test patch). Use [AUDIT_ORCHESTRATION.md](AUDIT_ORCHESTRATION.md) when you need
a per-run subagent-classified report instead of a single sweep.

---

## Phase 1 — parallel baseline sweep

The baseline arm is the diagnostic instrument: it has every native tool, so any
non-PASS verdict is *not* "the agent can't write code." Run baseline only —
running other arms first muddles the env signal.

```bash
# 1a — warm the OverlayFS cache for the target set (clone + venv per instance).
#      Cold cache + 50 instances = ~5 min at concurrency 4.
FILTER=$(ls problems/swe/<set>/*.yaml | xargs -n1 basename | sed 's/\.yaml$//' | paste -sd,)
python -m swebench cache setup --concurrency 4 --filter "$FILTER" 2>&1 | tee /tmp/cache.log

# 1b — baseline sweep into a dedicated output dir.
#      --parallel 4 is the safe default on 8 cores / 23 GiB; --parallel 6 risks
#      OOM on simultaneous heavy test suites (sympy/sklearn).
mkdir -p runs/swebench/validation_<DATE>
python -m swebench run \
  --arms baseline --runs 1 --parallel 4 \
  --filter "$FILTER" \
  --output-dir runs/swebench/validation_<DATE> \
  --resume \
  2>&1 | tee /tmp/sweep.log
```

Wall time on `verified-mini` (50 instances): ~3 hours. Cost: ~$25.

---

## Phase 2 — triage verdicts

```bash
python -m swebench analyze summary \
  --results-dir runs/swebench/validation_<DATE> \
  --out runs/swebench/validation_<DATE>/summary.csv
```

Sort each verdict bucket and inspect the failure signatures:

```bash
# per-instance verdict tally
for f in runs/swebench/validation_<DATE>/*_test.txt; do
  v=$(tail -n 5 "$f" | grep -Eo '^(PASS|FAIL|env_fail)$' | tail -1)
  echo "$v ${f##*/}"
done | sort | uniq -c

# extract the first error line per FAIL — quickest way to cluster signatures
for inst in $FAILS; do
  sig=$(grep -hE "^(E\s|ERROR |FAIL: |AssertionError|sphinx\.errors|ModuleNotFoundError|ImportError|VersionRequirement)" \
        runs/swebench/validation_<DATE>/${inst}_baseline_run1_test.txt | head -1)
  echo "$inst :: $sig"
done
```

**Bucket the verdicts:**

| Verdict | Meaning | Action |
|---|---|---|
| `env_fail` | Pre-flight `pytest --collect-only` returned 0 items. Agent never ran. | Fix env. |
| `FAIL` with import / `VersionRequirementError` / missing fixture | Collection succeeded but runtime exploded — *hidden* env failure. | Fix env. |
| `FAIL` with assertion error against the new test patch | Real agent miss. | Leave alone. |
| `ERROR` | Harness crash, auth issue, wall-time kill. | Investigate; usually env. |

**Group the env failures by root cause**, not by instance. PR #263's grouping:

1. Missing `roman` pkg — 8 instances
2. `types.Union` ImportError (Python 3.10+ guard typo) — 4 instances
3. `sphinxcontrib-* >= Sphinx 5` gate — 6 instances
4. `RemovedInSphinx40Warning` symbol deleted upstream — 1 instance
5. Bad YAML / pytest node-id / regex / shell-quoting bugs — 1 instance + 3 harness bugs

Open **one issue per root cause** (cluster, not instance) so the fix scope is
discoverable later. Tag the affected instance list in each.

---

## Phase 3 — batch-fix in a single PR

One PR covering all the env-fix issues from the sweep. Why batched, not 5
separate PRs:

- The verification loop (Phase 4) requires rebuilding the cache + re-running
  the affected instances. Doing that per-PR multiplies wall-time by 5×.
- Reviewers can see the whole sweep's logic in one place.
- Some fixes are causally linked (one unblocks another — see Phase 4 below).

**Use subagents to diagnose the trickier root causes in parallel** (read-only
diagnosis, not implementation). Example briefs are in the
[PR #263 transcript](https://github.com/hyang0129/onlycodes/pull/263) — three
parallel subagents diagnosed #260, #261, #262 while the main loop continued
applying the easier #258/#259 fixes.

For each root cause, the fix usually lives in one of these tables (per
[CLAUDE.md](../CLAUDE.md), `swebench/harness.py`):

| Table | When to edit |
|---|---|
| `_INSTANCE_PYTHON` | Instance needs a non-default Python (e.g. 3.9 for old sklearn / sphinx). |
| `_INSTANCE_PRE_INSTALL` | Packages to install before `pip install -e .`. |
| `_INSTANCE_POST_INSTALL` | Packages to **re-pin** after `pip install -e .` overrides them (very common with `sphinxcontrib-*`). |
| `_INSTANCE_SOURCE_SEEDS` | Tiny source patch applied before tests. Use when no PyPI version is in the safe zone (PR #263's 9698 case). |

Add a **test per root cause** in `tests/test_harness_venv.py` so the pin can't
silently get reverted later.

---

## Phase 4 — iterative verification (this is the trick)

After applying the batch fix, rebuild the cache for the changed instances and
**rerun only the affected subset** of the sweep:

```bash
# Force rebuild — the existing cache has the OLD pins.
python -m swebench cache setup --concurrency 4 --force --filter "$AFFECTED" \
  2>&1 | tee /tmp/rebuild.log

# Rerun baseline on the same subset into a fresh output dir.
mkdir -p runs/swebench/validation_<DATE>_postfix
python -m swebench run \
  --arms baseline --runs 1 --parallel 4 \
  --filter "$AFFECTED" \
  --output-dir runs/swebench/validation_<DATE>_postfix \
  --no-resume \
  2>&1 | tee /tmp/postfix.log
```

**Expect new failures to surface on the rerun.** Earlier env errors often hide
later ones — the first error to fire is the only one reported, so fixing it
exposes whatever the next layer's broken dep does. PR #263 saw three rounds:

| Round | Sweep result | What it surfaced |
|---|---|---|
| Pre-PR | 10 env_fail, 6 hidden FAIL, 0 PASS (out of 16) | The 5 buckets above. |
| Round 1 (#258+#259 only) | 5 PASS, 2 legit FAIL, 4 new sphinxcontrib hits, 1 regex bug | `roman` + `python3.9` unblocked collection → exposed `sphinxcontrib` gate (already part of #260) and a `_NODE_ID_LINE_RE` regex bug that mis-classified parametrized node IDs. |
| Round 2 (full PR + 9698 floor bump) | 4 PASS, 1 FAIL (alabaster on 7748) | The sphinxcontrib pins didn't cover `alabaster`, a *different* package family with the same Sphinx-≥-X gate pattern. Also discovered 9698 had no safe PyPI version → pivoted to a source-seed patch. |
| Round 3 (alabaster pin added to 7748) | PASS | Clean. |

**Each round = commit, force-push the PR branch, rerun the diagnose loop.**
Don't open a new PR per round — the PR body and a final verification comment
capture the full history.

Stop when the affected subset shows: `0 env_fail + 0 import-error-FAIL`. Any
remaining FAILs should look like genuine agent misses (assertion errors,
TypeError from incomplete fixes, etc.).

---

## Phase 5 — finalize

```bash
# Verify the full non-integration suite hasn't regressed.
python -m pytest tests/ -m "not integration" -q

# Post the per-instance result table as a PR comment so the reviewer can
# trace the loop. Format used by #263:
#
#   | Instance | Round-1 | Round-2 | Round-3 | Fix applied |
#   |---|---|---|---|---|
#   | sphinx-7590 | env_fail (roman) | PASS | — | #258 |
#   | ...
gh pr comment <PR> --body-file final_report.md

gh pr merge <PR> --squash --delete-branch
```

---

## Gotchas

- **`shell=True` in `run_tests` vs `subprocess.run([...])` in `run_preflight_collect`.**
  Quoting that survives the shell may shred at preflight (PR #263's `shlex.split` fix). Test both paths.
- **Cache invariants are strict.** Per [CLAUDE.md](../CLAUDE.md), an instance's cache must be `--force`-rebuilt whenever its pin tables change. Skipping the rebuild silently runs the OLD pins.
- **Wall-time cap is required.** Without [#257](https://github.com/hyang0129/onlycodes/pull/257)'s `wall_timeout_seconds` enforcement, an agent that hangs inside a tool call will run forever (PR #263 lost ~70 min to a sphinx-7590 hang). Verify the cap is on `main` before starting Phase 1.
- **Don't merge env fixes that aren't verified.** A pin you "think" is right is not the same as a pin you've watched the rerun PASS on. The loop is cheap — use it.

---

## References

- Canonical example: [PR #263](https://github.com/hyang0129/onlycodes/pull/263) and issues [#258](https://github.com/hyang0129/onlycodes/issues/258), [#259](https://github.com/hyang0129/onlycodes/issues/259), [#260](https://github.com/hyang0129/onlycodes/issues/260), [#261](https://github.com/hyang0129/onlycodes/issues/261), [#262](https://github.com/hyang0129/onlycodes/issues/262).
- Wall-time cap: [PR #257](https://github.com/hyang0129/onlycodes/pull/257) / Issue #223.
- Sweep mechanics: [BATCHED_RUN_SWE.md](BATCHED_RUN_SWE.md).
- Per-run subagent audit (different tool, similar goal): [AUDIT_ORCHESTRATION.md](AUDIT_ORCHESTRATION.md).
