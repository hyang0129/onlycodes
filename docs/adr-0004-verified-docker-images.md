# ADR 0004 — Run SWE-bench Verified from Official Prebuilt Docker Images

**Status:** Accepted (pending the C2 de-risk spike — see Reversibility).
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
tests inside containers.** This is the only path to **frozen reproducibility + exact
parity with published SWE-bench numbers, with zero coverage gaps** — precisely what the
conda-on-host path structurally cannot deliver.

Two non-negotiable framings:

- **Reproducibility comes from *pulling* the frozen images, not from Docker-in-Docker.**
  Building the images locally from the upstream Dockerfiles re-runs `conda env create` at
  build time and reintroduces the same drift. **We pull; we do not build.**
- **#311 is not wasted.** Conda-native build becomes the **fallback** for instances without
  a published image (or future custom, non-SWE-bench tasks). The rest of #311 — the vendored
  specs, `test_cmd` / `eval_commands` resolution, the official log-parser grading, the
  validator harness, and the analysis pipeline — all still apply on the image path.

## Why images (not "just fix more conda bugs")

- **Closes the structural tail, not just the bug tail.** Conda re-resolution and no-root
  system deps are *not* bugs; the frozen image makes both moot by construction.
- **Stops the per-instance fidelity treadmill.** 500 instances × per-spec quirks
  (qhull-from-source, env.yml solves, 3.5/3.6/3.7 provisioning, locale/root steps) are all
  pre-solved and frozen in the images SWE-bench already debugged across the dataset.
- **Exact published-number parity.** Running the canonical environment makes our pass-rates
  directly comparable to the literature — valuable for an archival paper (#298).
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
- **C2 (#316) — De-risk spike.** Actually `docker pull` a *failing-for-us* matplotlib image,
  run one in-container agent turn + a test, capture the transcript. The only unverified link
  is the real pull (vs the manifest existing); this is the go/no-go before the rewrite.
- **C3 (#317) — Container runtime + per-arm reset.** Pull/run/stop per instance; expose
  `/testbed`; git-history strip inside; **fresh container per arm** replaces the overlay
  refresh; pull-on-demand + prune to bound disk.
- **C4 (#318) — In-container agent execution.** Claude Code + the MCP exec-server inside the
  container; tool restriction for `code_only`/`onlycode` (mirror
  `runner.py:build_tools_flags`); isolated Claude config; JSONL transcript captured to the
  host; no grader/transcript leak.
- **C5 (#319) — In-container test execution + gold-patch fidelity gate.** Apply `test_patch`,
  run `eval_commands` + `test_cmd`, parse via the official `MAP_REPO_TO_PARSER`; add the
  **gold-patch transition gate** (gold patch flips `FAIL_TO_PASS`→pass, `PASS_TO_PASS` stays
  green) as the real fidelity metric; **pin images by digest**, not `:latest`.
- **C6 (#320) — Parity validation + conda fallback + docs.** Image-vs-conda on the coverage
  sample; image-if-published-else-conda selection rule; update CLAUDE.md / README / ADR.

### Invariants to preserve in-container

The onlycodes integrity invariants must hold **inside** the container:

- **Git-history strip** at `/testbed` — single orphan, no reflog (mirror
  `test_harness_strip.py`); the agent must not recover the fix via `git log`.
- **Tool restriction** for the code-execution-only arm (`--disallowedTools` + exec-server
  only).
- **Isolated Claude config** (`CLAUDE_CONFIG_DIR`; `.credentials.json` + `.claude.json` only;
  `--dangerously-skip-permissions --no-session-persistence`); credentials never persist into
  an image/commit.
- **No grader/reference/transcript leak** into the agent's view of `/testbed`.

## Consequences

- **`cache.py` / `venv_overlay` / `setup_conda_env` move off the Verified hot path.** The
  overlay machinery is replaced by fresh-container-per-arm. Conda-native remains for the
  fallback selection branch; the venv path stays for non-Verified sets.
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

- [ ] C2 spike confirms a real pull + in-container agent turn + parsed test (go/no-go).
- [ ] Container runtime with in-container git-strip and fresh-container per-arm reset (C3).
- [ ] Both arms run in-container with correct tool restriction + transcript capture (C4).
- [ ] Official-parser grading + gold-patch fidelity gate + digest pinning (C5).
- [ ] Image-vs-conda parity table + image-else-conda selection rule + docs updated (C6).
- [ ] This ADR's status flipped once the spike confirms (or rolled back per Reversibility).
