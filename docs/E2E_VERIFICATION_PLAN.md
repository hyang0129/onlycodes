# E2E verification of the Verified-buildable set (#308)

The gold-gate proved the **image + gold-patch grading** path for the 496
buildable instances. It does **not** exercise the **agent arm**: `run_agent`
(stage surface → invoke codex/claude → capture diff), `grade_agent_run`
(no-leak check → apply held-out test patch → faithful reinstall (Fix B) → eval →
grade), and transcript → cost/turns extraction. "Working e2e" means *that* path
runs cleanly across the set and grades sanely. This plan verifies it
cost-effectively, tiered cheap→expensive, gating each tier on the previous.

Scope to the buildable set everywhere: `--filter @sets/verified-buildable.txt`,
`--runtime image`. Always `--runs 1 --resume`; keep the 100 GB disk floor
(`ONLYCODES_MIN_FREE_GB=100`) and the Docker Hub token loaded.

## Tier 0 — grader brackets (≈ free, no agent tokens)

Confirm the agent-arm grader brackets correctly before spending on a real agent.

- **Empty-agent (no change) → expect ~0% PASS.** An agent that edits nothing must
  leave FAIL_TO_PASS red → `grade_agent_run` returns RESOLVED_NO for all. If any
  instance "passes" with no change, the held-out test patch / no-leak check is
  broken. *(Run a tiny stub agent, or a handful of instances; the point is the
  grading verdict, not the agent.)*
- **Gold-agent (apply gold as the agent's diff) → expect ~100% PASS** on the 496.
  This is the agent-arm analogue of the gold-gate and exercises
  `grade_agent_run` + the Fix B reinstall end-to-end. Divergence from ~100% here
  = an agent-arm grading bug (since the gold-gate already passed these).

Pass criterion: empty ≈ 0%, gold ≈ 100% on a 1-per-repo sample (~12). Any
instance that breaks the *bracket* is a harness bug, not an agent result.

## Tier 1 — codex baseline smoke (cheap: ~12–15 instances)

Stratified sample, one per repo (covers every conda env / parser / test runner):

```sh
set -a; . ./.env; set +a; export ONLYCODES_MIN_FREE_GB=100
python -m swebench run --runtime image \
  --agent-surface codex_cli --codex-model gpt-5.5 \
  --arms baseline --filter @sets/sample-1per-repo.txt \
  --runs 1 --parallel 1 --max-wall-seconds 1800 \
  --output-dir runs/swebench/codex_smoke
```

Verify (the things the gold-gate could not):
1. **No harness errors** — every instance pulls, prepares, runs codex, grades; no
   ERROR verdicts from infra (distinguish ERROR-infra from FAIL-unsolved).
2. **Agent plumbing** — codex actually ran (non-empty transcript), produced a
   diff, tool-gating applied; cost + turns populated in each record.
3. **Fix B in the agent arm** — pick the pylint/astropy envs; confirm the
   reinstall ran (no `appdirs`-class failures) and grading is sane.
4. **Sane pass rate** — `0% < pass < 100%` (codex baseline solves *some*). All-0
   or all-pass signals a plumbing bug, not model skill.

Gate: Tier 1 clean → proceed. Budget ~1 codex run × ~15 instances.

## Tier 2 — full codex baseline (the real data + final e2e proof)

```sh
python -m swebench run --runtime image \
  --agent-surface codex_cli --codex-model gpt-5.5 \
  --arms baseline --filter @sets/verified-buildable.txt \
  --runs 1 --parallel <N> --resume \
  --output-dir runs/swebench/codex_baseline_v1
```

- `--resume` skips completed triples → safe to stop/restart across rate-limit
  windows and the periodic docker-daemon restarts (re-`chmod` the socket +
  relaunch; nothing lost). Mirrors the gold-gate's resumable design.
- `--parallel N`: bounded by host CPU and the Docker Hub pull budget (images are
  cached from the gold-gate, so re-pulls should be minimal — reuse-forever).
- Effective-cost watch: cache-adjusted cost + input/output tokens per record.

Done = 496/496 have a baseline verdict with no infra ERRORs. Pass *rate* is a
result, not a gate; the e2e claim is "every buildable instance runs and grades
cleanly through the agent arm."

## Why this is effective

- **Tier 0 spends ~nothing** yet proves the grader brackets (the highest-risk
  harness piece) across the set.
- **Tier 1** catches every agent-surface/plumbing bug on ~15 instances before
  committing to the full spend — one per repo covers all env/parser variety.
- **Tier 2** is then pure data collection with high prior confidence; `--resume`
  makes it robust to interruptions.

A single full codex baseline (Tier 2) doubles as the first real benchmark arm —
verification and data collection are the same run.
