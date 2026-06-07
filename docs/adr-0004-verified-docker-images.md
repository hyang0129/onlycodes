# ADR 0004 — Run SWE-bench Verified from Official Prebuilt Docker Images

**Status:** Accepted. C1–C5 complete; C6 in progress. C2 de-risk spike — **GO**
(`docs/spike-c2-docker-images.md`, #316). C3 reset strategy decided (see below).
**Amended 2026-06-07 → image-only** (see "Update" below).
**Date:** 2026-06-04.
**Tracking issue:** [#314](https://github.com/hyang0129/onlycodes/issues/314).
**Supersedes:** the *build half* of [#311](https://github.com/hyang0129/onlycodes/issues/311) / PR [#313](https://github.com/hyang0129/onlycodes/pull/313) (conda-native build) for Verified. Conda/overlay is **deprecated** (see Update).

## Update (2026-06-07) — image-only; conda/overlay deprecated

The original plan kept a **dual-backend** `image-if-published-else-conda` selection rule
and a C6 image-vs-conda parity table. A coverage check across **all 500** Verified
instances (Docker Hub repo API) returned **500/500 published, 0 missing** — so the
`else-conda` branch never fires for Verified. Combined with the C5 gold gate giving
*absolute* fidelity against the official parsers (a stronger check than any conda
comparison), the conda/overlay path is **dead code for the benchmark** (overlay is
SWE-bench-only; artifact mode uses its own materialize path).

**Revised decision:** the harness is **image-only** for Verified. `run.py` defaults to
`--runtime image`; `--runtime overlay` is retained but emits a deprecation warning and is
slated for removal in a separate cleanup. Consequences: the C6 **parity table is dropped**
(nothing faithful to compare against), the standalone **conda gold gate (#322) is
unnecessary**, and the selection rule reduces to "image, else error loudly" (digest
pinning, #319, covers reproducibility; availability is the only residual risk). C5's
gold-fidelity sample stands at 12/12 RESOLVED_FULL across 7 repos. The lone empty-directive
instance in all of Verified is django-10097 (1/500; full-suite isolation residual, #337).

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
  **Implemented (`swebench/image_store.py`):**
  - *Pull-by-digest* — `resolve_remote_digest` (`buildx imagetools inspect`, **no pull**)
    pins `:latest`→`repo@sha256:…`; digests vendored in
    `swebench/data/verified_image_digests.json` (backfill: `scripts/resolve_image_digests.py`).
  - *Measured disk + layer profile* (profiled 2026-06-06, requests/matplotlib/django/sympy,
    10 django + 10 sympy pulled to verify dedup). Each image = ~15 content layers in three tiers:
    | tier | layer | size | shared scope |
    |---|---|---|---|
    | base | ubuntu + apt + miniconda | ~1.5 GB | **all images** (every repo) |
    | env | `setup_env.sh` (conda env) | django ~1.2 GB · mpl 1.7–3.8 GB | **same repo+version** |
    | instance | `setup_repo.sh` (/testbed + build) | **django ~0.32 GB · sympy ~0.3 GB · mpl ~2.65 GB** | **unique per instance** |
    Sharing is real and large: **10 django images added only ~3.6 GB** (vs 39.6 GB nominal, ~91%
    saved); each additional same-version instance is **~0.2–0.3 GB** (just its thin instance layer).
    matplotlib is the heavy outlier — its env bakes a full GUI/render stack (PyQt5 + wxPython + Qt
    runtime) and its repo layer carries image-comparison baselines, so it is 2–3× a typical image.
    **Grounded full-500 deduped cache ≈ ~400 GB** (base once + ~100 GB of per-repo-version envs +
    ~290 GB of per-instance layers) — firmly **sub-TB**, dominated by matplotlib + the env spread,
    *not* the django/sympy bulk. A single pass never needs the whole cache; the 150 GB cap holds
    hundreds of django/sympy or ~15–20 matplotlib at once.
  - *Disk policy* — **default cap 150 GB** (`ONLYCODES_IMAGE_CAP_GB`); `ensure_image` pulls on
    demand and `prune_to_cap` LRU-evicts prepared snapshots + base images (after reclaiming
    dangling images/stopped containers) to stay under cap. `group_by_repo_version` clusters a
    repo's instances so its shared layer is reused before eviction (minimises re-pulls).
  - *Auth — token now, mirror later.* `registry_login` uses `ONLYCODES_DOCKERHUB_TOKEN`
    (token via stdin, never argv) for a higher pull limit; pulls retry on `toomanyrequests`
    with exponential backoff. A **registry:2 pull-through cache** is the documented scale-up for
    the full 500-image sweep (each image hits Hub once; re-pulls after prune served locally) —
    deferred until the sweep is actually run (needs host dockerd `registry-mirrors` config).
  - *Op note (C1 follow-up):* the DooD socket reverts to `root:root 0660` on a host Docker
    Desktop restart; `vscode` then needs re-adding (post-create `chmod a+rw /var/run/docker.sock`).
    Not a C3b code concern, but it gates any image-runtime run.
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
- [x] Both arms run in-container with correct tool restriction + transcript capture (C4/C4b).
- [x] Official-parser grading + gold-patch fidelity gate + digest pinning (C5).
- [ ] ~~Image-vs-conda parity table + image-else-conda selection rule~~ → **image-only**
  (100% image coverage; see Update 2026-06-07): image default + overlay deprecated + docs (C6).
- [ ] This ADR's status flipped once the spike confirms (or rolled back per Reversibility).
