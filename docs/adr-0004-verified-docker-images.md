# ADR 0004 — Run SWE-bench Verified from Official Prebuilt Docker Images

**Status:** Accepted. C2 de-risk spike complete — **GO** (`docs/spike-c2-docker-images.md`,
#316). C3 reset strategy decided (see below).
**Date:** 2026-06-04.
**Tracking issue:** [#314](https://github.com/hyang0129/onlycodes/issues/314).
**Supersedes:** the *build half* of [#311](https://github.com/hyang0129/onlycodes/issues/311) / PR [#313](https://github.com/hyang0129/onlycodes/pull/313) (conda-native build) for Verified. Conda is retained as a fallback.

## Context

WS-A.2.1 (#311) made the Verified build faithful by **re-resolving** each instance's
environment on our host from the official `MAP_REPO_VERSION_TO_SPECS` — a conda env per
`(repo, version)` built via micromamba (`setup_conda_env`). The P2-δ coverage run (full
inventory in #313) built a stratified 38-instance sample covering all 7 Python versions,
all 4 packages-kinds, and all 12 repos. Result: **26/38 buildable, 32/38 built** — and,
critically, the residual failures cluster into a small set of causes that are **structural,
not bugs**:

| Class | Hits | Nature |
|---|---|---|
| `pre_install` shell-state lost across commands | matplotlib ×3 | **bug** (fixable — run as one script) |
| `environment.yml` won't conda-solve today | matplotlib ×2 | **structural** — conda-forge drifted since the image was frozen |
| `environment_setup_commit` unreachable on reset | pylint ×1 | bug (fetch depth) |
| in-place C extensions invisible to Gate-2 clone | sklearn ×4 | validator limitation (not a build failure) |
| parametrized test-id "not found" | pylint ×1 | Gate-2 resolution |
| malformed `test_cmd` in materialized YAML | django ×1 | materialization |

Two of these are not closable by bug-fixing on the host model:

1. **Frozen artifact vs re-resolution.** SWE-bench built each environment image **once**
   and froze it. Running `conda/micromamba create` from the same `environment.yml` *today*
   resolves against a **moved conda-forge** — the solve can fail outright (matplotlib) or
   succeed to **drifted versions** the benchmark was never validated against. Our code is
   correct; the world changed.

2. **No-root system dependencies.** Specs `apt-get`-install system libraries (freetype,
   qhull headers, ffmpeg, …) as root in the image. On the host we have no per-instance root
   and cannot isolate `/`, so these are skipped — fine for many instances, fatal for some.

We also never measure the bar that actually matters: whether the **gold patch** flips
`FAIL_TO_PASS`→pass in our environment. "Buildable" overstates true fidelity.

### The frozen images exist for the whole set

Verified **2026-06-04** by querying Docker Hub's registry API directly (anonymous token +
manifest request; no Docker needed):

- **500 / 500** Verified spine instances are published at
  `swebench/sweb.eval.x86_64.<instance_id.lower(), "__"→"_1776_">:latest` — including
  *every* instance that failed for us. Zero 404s, zero gaps.
- Compressed image size ~**1.0 GB** (requests) … ~**3.2 GB** (matplotlib). The 15 layers
  **share**: one base (Ubuntu 22.04 + miniconda + node), ~60 per-`(repo, version)` env
  layers, and a thin per-instance repo layer. On-disk for the whole set is **~100–200 GB**,
  not 500 × 3 GB.
- In-image canonical paths: repo at `/testbed`, conda env at `/opt/miniconda3/envs/testbed`,
  user `root`.

So the frozen artifacts the conda path can never reproduce *already exist and are pullable
for 100% of the set*.

## Decision

**Migrate Verified execution to pull the official prebuilt images and run the agent +
tests inside containers.** This is the only path to **frozen reproducibility + environment
parity with zero coverage gaps** — precisely what the conda-on-host path structurally
cannot deliver.

Three non-negotiable framings:

- **Environment parity, not leaderboard equality.** Running the canonical environment
  *removes the environment as a confound*; it does **not** make our pass-rate equal a
  specific published leaderboard row — our agent/scaffold differs from those submissions.
- **Reproducibility comes from *pulling* the frozen images, not from Docker-in-Docker.**
  Building the images locally from the upstream Dockerfiles re-runs `conda env create` at
  build time and reintroduces the same drift. **We pull; we do not build.**
- **#311 is not wasted, but the fallback is dual-backend.** Conda-native build becomes the
  **fallback** for instances without a published image (or future custom, non-SWE-bench
  tasks); the vendored specs, `test_cmd` / `eval_commands` resolution, official log-parser
  grading, validator harness, and analysis pipeline all still apply. Keeping it means
  `run.py` carries **both** execution backends (container + conda/overlay) under an
  *image-if-published-else-conda* rule — dual-backend maintenance, not a clean replace.

## Why images (not "just fix more conda bugs")

- **Closes the structural tail, not just the bug tail.** Conda re-resolution and no-root
  system deps are *not* bugs; the frozen image makes both moot by construction.
- **Stops the per-instance fidelity treadmill.** 500 instances × per-spec quirks
  (qhull-from-source, env.yml solves, 3.5/3.6/3.7 provisioning, locale/root steps) are all
  pre-solved and frozen in the images SWE-bench already debugged across the dataset.
- **Removes the environment confound.** Running the canonical environment means a pass-rate
  difference is attributable to the agent/scaffold, not to env drift — valuable for an
  archival paper (#298). (This is env parity, not equality with a specific leaderboard row.)
- **Stronger isolation.** A container is a better sandbox than overlay + conda-on-host,
  aligned with the benchmark-integrity posture in CLAUDE.md.
- **The freezing we want, we get for free.** A pulled image *is* the frozen env; our cache
  already gave us per-instance freezing on first build, but only for envs that solved at
  all today — the image removes the "won't solve today" failure mode entirely.

### Why not the alternatives

- **Keep conda-native only.** Leaves the structural tail unreproducible and keeps us
  maintaining a re-implementation of SWE-bench's build that chases upstream. Rejected as the
  *primary* path; retained as fallback.
- **DinD-build the images locally.** Gains root + `/testbed` + system deps but **reintroduces
  conda drift** — no frozen-reproducibility win. Rejected.
- **Docker-as-env-builder, host execution (extract the env to the host).** Conda envs bake
  absolute paths (`/opt/miniconda3/envs/testbed`); relocating to the host re-opens the
  shebang-relocation problem the overlay design already fights. More Frankenstein than
  full-container execution, for no reproducibility gain. Rejected.

## Implementation

Decomposed into child issues on #314:

- **C1 (#315) — Docker access.** There is no Docker in the dev container today (no CLI, no
  socket). Decide **DinD-in-devcontainer** (host socket mount / DinD sidecar) vs
  **host-orchestration** (run the orchestrator on the WSL2 host with native Docker, no
  nesting). Per CLAUDE.md, read `~/.claude/guides/devcontainer-guide.md` before any
  devcontainer change. *Prereq — gates everything.*
- **C2 (#316) — De-risk spike + early measurement.** Actually `docker pull` a *failing-for-us*
  matplotlib image, run one in-container agent turn + a test, and verify the exec-server's
  `unshare` net-iso works in-container. **Also measure** pull size/time, container spin-up,
  and per-arm reset throughput — the numbers that decide C3's reset strategy and grid
  feasibility. Go/no-go before the rewrite.
- **C3 (#317) — Container runtime + per-arm reset.** Pull/run/stop per instance; expose
  `/testbed`; git-history strip inside. **Reset strategy — DECIDED (settled by C2's numbers):
  prepare-once + `docker commit` a stripped snapshot, then per-arm reset = fresh container
  from that snapshot.** Rationale: the official image carries full upstream history (incl. the
  fix), so the strip is mandatory; C2 measured strip at **~2.0 s** on matplotlib's 42k-commit
  history (`git repack` dominates) vs. a fresh-container reset at **~286 ms**. Baking the strip
  into the snapshot pays it **once per instance** instead of once per arm (×arms×seeds×500), and
  a fresh container is pristine by construction — no in-place reset, no cross-arm leakage, and
  no checkpoint/restore complexity. Delivered as `swebench/container.py`
  (`prepare_instance`/`start_arm_container`/`reset_arm`/`exec_in`/`copy_in`/`copy_out`/`teardown`)
  + `test_container_strip.py`; gated behind `--runtime image`. Files move by `docker cp`, **not
  bind-mounts** (under DooD the `-v` source resolves on the docker host — C2 finding).
- **C3b (#323) — Image + registry + disk management.** Pull-by-digest; Docker Hub
  rate-limits/auth/bandwidth (~1 TB for the set); optional registry mirror; prune/disk.
- **C4 (#318) — In-container *Claude* agent execution.** Claude Code + the MCP exec-server
  inside the container; tool restriction (mirror `runner.py:build_tools_flags`); isolated
  config/creds; **preserve the exec-server's executed-code network isolation**. (Codex is the
  follow-up #325; output capture is C4b #324.)
- **C4b (#324) — Agent output capture.** JSONL transcript + result out to the host, no-leak.
- **C5 (#319) — In-container test execution.** Apply `test_patch`, run `eval_commands` +
  `test_cmd`, parse via the official `MAP_REPO_TO_PARSER`; **pin by digest + arch**; reuse the
  gold-patch gate (now standalone **#322**) against the image path.
- **C6 (#320) — Parity + dual-backend selection + docs.** Image-vs-conda (buildable +
  gold-faithful) on the #313 sample; image-if-published-else-conda rule; update CLAUDE.md /
  README / ADR.

A **standalone, non-blocking** issue feeds the decision: **#322 — gold-patch transition gate
on the existing validator** (quantifies the conda baseline's *fidelity*, not just buildable;
C5 reuses it). Decoupled so the evidence that justifies/de-justifies this epic isn't gated
behind the migration itself.

### Invariants to preserve in-container

The onlycodes integrity invariants must hold **inside** the container:

- **Git-history strip** at `/testbed` — single orphan, no reflog (mirror
  `test_harness_strip.py`); the agent must not recover the fix via `git log`.
- **Tool restriction** for the code-execution-only arm (`--disallowedTools` + exec-server
  only).
- **Executed-code network isolation.** Preserve the exec-server's `unshare -n` no-network
  sandbox for code the agent *runs* (the cheat boundary). The agent process itself keeps API
  network — it must, to reach the model — so this is *not* `--network none` on the container;
  only *executed code* is isolated, matching the host implementation. C2 verifies the
  `unshare` mechanism still works under Docker (it may need a cap/seccomp adjustment).
- **Isolated Claude config** (`CLAUDE_CONFIG_DIR`; `.credentials.json` + `.claude.json` only;
  `--dangerously-skip-permissions --no-session-persistence`); credentials never persist into
  an image/commit.
- **No grader/reference/transcript leak** into the agent's view of `/testbed`.

## Consequences

- **`cache.py` / `venv_overlay` / `setup_conda_env` move off the Verified *primary* hot
  path** (but stay live for the conda fallback branch — `run.py` is dual-backend). The
  overlay reset is replaced by the C3 reset strategy (chosen against C2's throughput numbers,
  not assumed). The venv path stays for non-Verified sets.
- **Disk profile changes** from conda envs (~150 GB) to pulled image layers (~100–200 GB),
  pull-on-demand + prune.
- **New dependency: a container runtime** in the environment (the C1 decision). This is the
  main feasibility risk and is de-risked first (C1 → C2).
- **Paper reproducibility improves** (frozen env + digest pinning + published-number parity)
  — directly relevant to #298. Record provider/registry + digest + access date for final
  runs.
- **One-time rewrite cost** in `run.py` / `runner.py` / `harness.py`, offset by retiring the
  per-instance build-fidelity work.

## Reversibility

The decision is **gated by C2 (#316)**: if the spike shows DinD/host-Docker is infeasible in
this environment, or pulls don't work as the manifests suggest, we **abort cheaply** before
any `run.py` rewrite and fall back to the conda-native path (#311), accepting and documenting
its structural shortfall (the env.yml-drift + no-root-system-dep tail). Because conda-native
is retained as a fallback (not deleted), reverting is a configuration choice, not a code
excavation. Until C2 is green, treat this ADR as a committed *direction* with an explicit
kill-switch, not an irreversible migration.

## Acceptance criteria (from #314)

- [x] C2 spike confirms a real pull + in-container agent turn + parsed test (go/no-go).
- [x] Container runtime with in-container git-strip and fresh-container per-arm reset (C3).
- [ ] Both arms run in-container with correct tool restriction + transcript capture (C4).
- [ ] Official-parser grading + gold-patch fidelity gate + digest pinning (C5).
- [ ] Image-vs-conda parity table + image-else-conda selection rule + docs updated (C6).
- [ ] This ADR's status flipped once the spike confirms (or rolled back per Reversibility).
