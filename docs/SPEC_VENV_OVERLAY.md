# SPEC: Per-arm venv overlay (`--venv-isolation`)

## Motivation

The cached venv at `instances/<id>/venv/` is shared across **all arms and all runs** of an instance. When the agent runs `pip install <foo>` during an arm, the install writes directly into the cached venv (which lives outside the repo overlay). Consequences:

1. **Intra-sweep cross-arm contamination.** If `onlycode` runs before `baseline`, anything the onlycode agent pip-installs is visible to baseline. The three arms of a sweep are not truly independent — a measurement-integrity bug.
2. **Inter-sweep cache poisoning.** The drift triggers `verify_lockfile` failure on the next sweep, forcing a full `setup_venv` rebuild. For heavy C++ extensions (matplotlib-26160) the rebuild OOM-kills `cc1plus` under `--parallel 4`, blocking the rerun entirely.

Both symptoms collapse into one root cause: the venv is mutable shared state.

This spec adds a per-arm overlay of the venv, mirroring the existing repo-overlay pattern. The cached venv becomes a frozen lowerdir; agent writes land in a per-arm upper layer that is discarded after the arm completes. Cache stays bit-identical; arms stay independent.

## Scope

- **In scope:** SWE-bench harness (`swebench/`). The artifact-graded harness has a different venv lifecycle (per-task scratch) and is out of scope.
- **Out of scope:** artifact mode, prompt-cache isolation (already covered by `--cache-isolation`), repo overlay (unchanged), agent-side tool restrictions.

## Design

### Layout change

Existing per-instance cache entry:
```
<cache>/instances/<id>/
  repo/              # already overlay'd at /tmp/<id>-eval/merged
  venv/              # shared, mutable, leaks across arms
  lockfile.txt
```

New layout when `--venv-isolation` is on:
```
<cache>/instances/<id>/
  repo/
  venv_lower/        # pristine cache, lowerdir only, never written
  venv/              # canonical path — fuse-overlayfs mountpoint, populated per-arm
  lockfile.txt
```

`venv/` is **the same path** as before. Code outside the cache module continues to refer to `cache_paths(id)["venv"]` and gets a working venv — the difference is that the venv is now a per-arm overlay merge instead of a shared directory.

**Why the same path:** venvs bake absolute paths into shebangs (`#!/cache/instances/<id>/venv/bin/python`). Mounting the merged view at any other path breaks every console script (`pip`, `pytest`, etc.). The rename `venv → venv_lower` lets us reuse `venv/` as the mountpoint without touching shebangs.

### CLI flag

Add to the `swebench run` Click command (mirror the `--cache-isolation` flag added in #294/#295):

```python
@click.option(
    "--venv-isolation/--no-venv-isolation",
    default=True,
    help="Mount per-arm fuse-overlayfs over the cached venv so agent pip "
         "installs don't poison the cache or cross-contaminate arms. "
         "Default: on. Disable with --no-venv-isolation to restore the "
         "legacy shared-venv behavior.",
)
```

Thread the bool through to the per-instance scheduler and into `_run_arm`. Do not introduce an env var as the primary control surface — keep the surface the CLI flag.

### Per-arm flow (`venv_isolation=True`)

In the existing per-arm setup path (currently `_run_arm` in [swebench/run.py](swebench/run.py)), before invoking the agent and tests, **wrap the entire arm in a venv-overlay context manager**:

```python
# pseudocode — implementer should match the existing overlay patterns in cache.py / run.py
with venv_overlay(
    instance_id=problem.instance_id,
    arm=arm,
    run_idx=run_idx,
    venv_lower=paths["venv_lower"],
    venv_merged=paths["venv"],          # canonical path, same as before
    upper_root="/tmp",                  # /tmp/<id>-<arm>-run<N>-venv/{upper,work}
) as venv_dir:
    reinstall_editable(venv_dir, repo_dir)   # existing call; now hits the merged venv
    run_claude(..., venv_dir=venv_dir)
    run_tests(..., venv_dir=venv_dir)
```

The context manager:
1. Creates `/tmp/<id>-<arm>-run<N>-venv/{upper,work}` (and ensures `venv_merged` exists as an empty mountpoint).
2. Mounts `fuse-overlayfs(lower=venv_lower, upper, work, merged=venv_merged)`.
3. Yields `venv_merged` as the venv_dir.
4. On exit (incl. exception): unmount via `fusermount3 -u`, then `rm -rf upper work` and the mountpoint scratch parent.
5. On unmount failure: log and continue; cleanup is best-effort, same as existing overlay teardown.

**Concurrency constraint:** the merged path is the canonical `cache/instances/<id>/venv`, shared across arms of the same instance. Today the harness serializes arms within an instance (parallelism is across instances), so this is fine. If intra-instance parallelism is added later, the merged path will need to become per-arm and the shebang relocation problem will need a separate solution. Document this in code.

### Per-arm flow (`venv_isolation=False`)

Use the existing shared-venv behavior unchanged. The legacy `verify_lockfile` + cache-rebuild branch stays alive on this path so old behavior is byte-identical when the flag is off.

### Cache-build path (`setup_venv`)

When `setup_venv` populates a cache entry, write to `venv_lower/` instead of `venv/` (only when isolation is enabled — see migration below). The on-disk layout decision is made by `cache_paths()`; `setup_venv` reads paths from there.

`has_cached_instance` must check `venv_lower/` exists (when isolation is enabled) instead of `venv/`. Same for `paths["venv"]` consumers that check `os.path.isdir(venv_dir)`.

### Migration

One-shot, on the fly, idempotent:

```python
def migrate_to_isolated_layout(instance_dir: str) -> None:
    """If a legacy `venv/` exists and no `venv_lower/`, rename. Otherwise no-op."""
    venv = os.path.join(instance_dir, "venv")
    venv_lower = os.path.join(instance_dir, "venv_lower")
    if os.path.isdir(venv) and not os.path.exists(venv_lower):
        # Must not be a fuse mountpoint at this moment.
        if _is_mountpoint(venv):
            raise CacheError(f"{venv} is currently mounted; cannot migrate")
        os.rename(venv, venv_lower)
```

Call this from `has_cached_instance` (or a wrapper) so the first run after upgrade migrates lazily. Do not require a separate `swebench cache migrate` command; lazy migration covers all real users.

When `--no-venv-isolation` is set, **do not migrate** — the legacy code path uses `venv/`. If a user toggles the flag back and forth, ensure both layouts can coexist or be rebuilt cleanly.

### Drift detection

Under `--venv-isolation`, the cache cannot be corrupted by an agent. The `verify_lockfile` branch in `run.py` becomes dead code on that path. Recommended: keep `verify_lockfile` as a **paranoia assertion** that fires only if isolation is on AND drift is somehow detected — that would indicate the overlay logic itself broke. Log loudly and fall through to rebuild for safety.

Under `--no-venv-isolation`, behavior is unchanged.

### Failure handling

| Failure | Behavior |
|---|---|
| `fuse-overlayfs` mount fails (permission, FUSE unavailable) | Log warning. Fall back to **direct copy** (`cp -a venv_lower /tmp/<id>-<arm>-run<N>-venv/copy`) and use the copy as venv_dir. Rewrite shebangs in copied scripts if needed (use `python -m venv --upgrade` or sed pass on `*/bin/*` shebangs). This is the rare/degraded path; correctness > performance. |
| Pre-existing stale mount on merged path | Attempt unmount + retry once. If still mounted, error out for that instance (do not silently fall back; this is a state bug worth surfacing). |
| Unmount fails on teardown | Log; mark for cleanup; do not fail the arm. |

These failure modes mirror the repo overlay's existing behavior — implementer should look at the existing fallback logic in `swebench/cache.py` and `swebench/run.py` for the exact patterns to copy.

## Invariants

Hard requirements that any implementation must preserve:

1. **Cache immutability under isolation.** After any arm with `--venv-isolation` completes, `venv_lower/` must be bit-identical to its pre-arm state. Verified by hashing `pip freeze` output (or directory tree hash) before/after.
2. **Cross-arm independence under isolation.** Within one sweep, arm N's pip installs must not be visible to arm N+1.
3. **Backward compat with `--no-venv-isolation`.** The shared-venv code path must be byte-identical to current behavior. Use this for parity testing.
4. **No new SWEBENCH_CACHE_ROOT semantics.** Cache root resolution is unchanged.
5. **Shebangs must work.** The merged venv path equals the path at which the venv was originally created. This is non-negotiable.
6. **Cleanup must happen on exception.** Use try/finally or a context manager. Orphan mounts have already bitten this project once (the 100 stale `/tmp/*-eval/merged` mounts).

## Tests

Add to `tests/test_cache.py` (unit) and `tests/test_run.py` or a new `tests/test_venv_overlay.py` (integration):

1. **Unit: layout migration.** Create a fake cache entry with legacy `venv/` layout, call the migration helper, assert `venv_lower/` exists and `venv/` no longer does. Idempotent on second call.
2. **Unit: `has_cached_instance` honors both layouts.** With isolation on: checks `venv_lower/`. With isolation off: checks `venv/`.
3. **Integration (`@integration`): cache immutability.** Build a real cache entry (small repo, e.g., one of the existing integration fixtures). Capture `sha256` of `find venv_lower -type f | xargs sha256sum`. Run one arm via stubbed `run_claude` that does `pip install requests` inside the venv. After arm completes and overlay is torn down, recompute the hash. Assert equal.
4. **Integration: cross-arm independence.** Two arms back-to-back. Arm 1 (stubbed) pip-installs `requests`. Arm 2 (stubbed) runs `python -c "import requests"`. Assert arm 2 raises `ModuleNotFoundError`.
5. **Integration: backward-compat.** Same scenarios with `--no-venv-isolation`. Cache immutability test should *fail* (or be skipped); cross-arm independence test should *fail* (or be skipped). This documents the bug the flag fixes.
6. **Regression guard in `tests/conftest.py`.** Ensure the autouse `patterns.json` immutability fixture still passes.

All integration tests use the existing fixture cache root (monkeypatched `SWEBENCH_CACHE_ROOT`), never the real cache.

## Code touch points

The implementer should read these before writing:

| File | Expected change |
|---|---|
| [swebench/cache.py](swebench/cache.py) | `cache_paths()` adds `venv_lower`; `has_cached_instance` updated; new `migrate_to_isolated_layout`; new `venv_overlay()` context manager (or extend existing overlay helpers); `setup_venv` writes to `venv_lower` when isolation is on. |
| [swebench/run.py](swebench/run.py) | New `venv_isolation: bool` plumbed from CLI to `_run_arm`. `_run_arm` wraps the existing arm body in `venv_overlay()` when on. `verify_lockfile` branch becomes a paranoia assert under isolation. |
| [swebench/cli.py](swebench/cli.py) | Add `--venv-isolation/--no-venv-isolation` flag to `swebench run`. |
| `tests/test_cache.py`, `tests/test_run.py`, new `tests/test_venv_overlay.py` | See "Tests" above. |
| [CLAUDE.md](CLAUDE.md) | Add a short paragraph under "Key Invariants" documenting the venv-overlay rule and the canonical-path-shebang constraint. |
| [README.md](README.md) | One-line mention in the CLI reference for the new flag. |
| Docstrings in [swebench/cache.py](swebench/cache.py#L16) | Update the "venv is **not** part of the overlay" comment — that's now only true with `--no-venv-isolation`. |

Do **not** edit:
- `patterns.json` (autouse fixture will fail).
- `paper/` (out of scope; paper writing has its own restrictions per CLAUDE.md).
- Any artifact-mode code (`swebench/artifact_*`, `swebench/_artifact_grade_runner.py`).
- `mcp-config.json` or `exec_server/` (orthogonal).

## Non-goals

- Per-task prompt-cache isolation (already done; `--cache-isolation`).
- Sandboxing `$HOME` (`~/.cache/pip`, etc.). Out of scope; mention in commit message as a known follow-up.
- Making intra-instance arms parallelizable. Spec preserves the current serial-arms-within-instance assumption.
- Removing or deprecating the `--no-venv-isolation` path. Keep it for parity testing and as an escape hatch.

## Acceptance

- New flag works; `swebench run --help` shows it.
- All existing tests pass.
- New tests above pass.
- A targeted manual rerun on one drift-affected instance (e.g., `mwaskom__seaborn-2946`) completes both arms without triggering `verify_lockfile` rebuild.
- Git diff stays inside the files listed in "Code touch points" (plus tests). No collateral edits.

## Out-of-band cleanup (not part of this change)

Before testing on the live machine, the 100 stale `/tmp/*-eval/merged` fuse mounts from prior crashed sweeps need to be unmounted manually:

```bash
mount | awk '/\/tmp\/.*-eval\/merged.*fuse-overlayfs/ {print $3}' | xargs -n1 fusermount3 -u
rm -rf /tmp/*-eval
```

This is an operational task, not a code change. The spec does not require the implementer to do it.
