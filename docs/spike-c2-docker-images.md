# C2 De-risk Spike — Run SWE-bench Verified from Official Prebuilt Docker Images

**Issue:** [#316](https://github.com/hyang0129/onlycodes/issues/316) · **Epic:** [#314](https://github.com/hyang0129/onlycodes/issues/314) · **ADR:** [adr-0004](adr-0004-verified-docker-images.md)
**Date:** 2026-06-05 · **Verdict: GO**

Validated end-to-end on ONE instance — `matplotlib__matplotlib-22865` (version `3.5`), chosen because the
conda-native build path (#311) **could not build it**. The published image runs it fine, which is the whole point.

## Correctness — all load-bearing links proven

| Link | Result |
|---|---|
| Published image pulls (auth/arch/decompress) | ✅ `docker.io/swebench/sweb.eval.x86_64.matplotlib_1776_matplotlib-22865:latest`, digest `sha256:4bb5781…` |
| Layout | ✅ repo at `/testbed`, conda env at `/opt/miniconda3/envs/testbed`, `import matplotlib` → `3.6.0.dev2064+gc730dda63b` |
| `/testbed` git state | ✅ HEAD is a `SWE-bench` commit layered **on top of** `base_commit` (`c6c7ec19…`, an ancestor) |
| Test patch applies + test runs + parses | ✅ test patch applies cleanly; 3 FAIL_TO_PASS tests **FAIL at base_commit** (correct, pre-fix), `3 failed in 2.16s` |
| **Exec-server network isolation in-container** | ✅ **BOTH** unshare strategies work — see below |
| One in-container agent turn + transcript on host | ✅ real Bash tool_use → tool_result → final text; `result` record: **cost $0.059, 2 turns, success**; transcript `docker cp`'d to host, parseable |

### Network isolation (the riskiest item) — RESOLVED, no fix needed
The exec-server's `unshare -n` requirement (hard-required in `exec-server.js`) works under Docker with the
`--cap-add=SYS_ADMIN` we already grant:
- Strategy A `unshare --user --map-root-user --net` (rootless) → executed code **ISOLATED** (URLError, no route)
- Strategy B `unshare -n` (needs CAP_SYS_ADMIN) → **OK**
- Control: same code **without** unshare reaches the network (HTTPError = server responded) → isolation result is meaningful.

The agent process keeps API network; only *executed code* is isolated — matches the host implementation.

## Measurements — sizing the design

| Metric | Value | Notes |
|---|---|---|
| Image, compressed | **3.01 GB** across 16 layers | manifest sum |
| Image, on disk | **11.2 GB** | uncompressed |
| Pull wall-clock | **320 s** (~5.3 min) | this connection; one-time per image, prefetchable |
| Container spin-up (cold create+start) | **1355 ms** | first start |
| **Per-arm reset (fresh `docker run -d`)** | **286 ms** | pristine `/testbed`, extensions intact |
| `docker cp` claude binary (234 MB) into container | **9.2 s** | one-time; bake into a derived image to avoid |
| In-container agent turn | 7 s / $0.059 / 2 turns | trivial probe prompt |

## Findings that shape C3+ (the rewrite)

1. **Reset = recreate the container, not overlay-refresh.** `docker run -d` on the already-pulled image gives a
   pristine `/testbed` in **286 ms** — comparable to today's overlay reset and conceptually simpler. No
   fuse-overlayfs, no git-history-strip needed (the image is the frozen ground truth). C3's reset strategy = fresh
   container per arm.
2. **Never `git clean -fdx` inside the image.** `-x` deletes the in-place compiled C extensions
   (`matplotlib/_c_internal_utils.so`) baked into the image, breaking imports until rebuilt. The host harness
   already guards this (`git_reset` cleans with `-e "*.so" -e "*.pyd"`); the image path sidesteps it entirely by
   recreating the container. If an in-place git reset is ever used instead, it MUST preserve `*.so`/`*.pyd`.
3. **DooD bind-mounts resolve on the Docker host, not in the dev container.** `-v /dev-container/path` silently
   creates empty mountpoints. Move files with `docker cp` (put_archive/get_archive) — which is exactly what the
   SWE-bench harness does. No bind-mounts in the rewrite.
4. **The agent can't run as root** (`--dangerously-skip-permissions` refuses uid 0, and SWE-bench images run as
   root). C4 must create/`useradd` a non-root user in the container and `chown` `/testbed` to it before invoking
   the agent. Conda env can stay root-owned (read+exec is enough; the editable install imports from `/testbed`).
5. **Image vs. re-resolution drift = the epic's thesis, confirmed.** The image ships matplotlib `3.6.0.dev` on
   Python 3.11; our conda re-resolution of version `'3.5'` would build something else. The frozen image is the
   authoritative environment — re-solving drifts.
6. **Disk is the binding constraint, not time.** 11.2 GB/image on disk (layers shared within a repo/version).
   The 500-image grid needs a disk budget + a prune/LRU strategy (C3/C5). Pull time (~5 min) is one-time and
   prefetchable; reset (286 ms) is cheap.

## Open items handed to C3+
- Bake claude (+ a non-root user) into a thin derived image to amortize the 9.2 s cp and the useradd/chown per run.
- Confirm the gold-patch GREEN transition (FAIL_TO_PASS→pass, PASS_TO_PASS stays green) as the real fidelity gate
  — standalone issue [#322], runs against the existing validator.
- Disk budget + image LRU/prune policy for the full grid (C3/C5).
