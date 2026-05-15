# Spec — Issue #244: Generate and validate Codex MCP config for codebox

**Epic:** [#217](https://github.com/hyang0129/onlycodes/issues/217) (Support Codex CLI as an additional agent surface) — Slice 4
**Unblocked by:** [#221](https://github.com/hyang0129/onlycodes/pull/221) (AgentRunner abstraction)
**Tier:** 1 (Simple — single area, settled architecture, < 200 lines)

---

## Problem

The Codex CLI agent surface landed in #221 with `CodexRunner._write_codex_config()` and `_resolve_bundle()`, but three portability/safety gaps remain that block reliable use outside the current dev container:

1. **`mcp-config.json` hardcodes container-specific paths.** `command` is pinned to `/usr/bin/node`; `args[0]` is an absolute path to `exec_server/dist/exec-server.bundle.mjs`; `cwd` is the workspace root. After a container rebuild or workspace move, `CodexRunner._resolve_bundle()` reads the stale JSON and silently falls back to the relative candidate computed from `runner.py`'s location — masking a real misconfiguration.
2. **No pre-flight check for the Codex bundle.** Missing or unbuilt bundle (`exec_server/dist/exec-server.bundle.mjs`) only surfaces mid-run, after the temp `CODEX_HOME` is set up and the agent has started.
3. **TOML rendered as an f-string is path-unsafe.** [swebench/runner.py:342-372](../../swebench/runner.py#L342-L372) interpolates `bundle_path` and `cwd` directly into TOML without escaping. Paths containing `"` or `\` produce invalid TOML; failures look like cryptic Codex startup errors.

## Goals

- `mcp-config.json` is portable across environments — either regenerable via CLI or built dynamically at runtime.
- Codex bundle misconfiguration is caught before the agent subprocess starts, with an actionable error.
- `_write_codex_config()` produces valid TOML for any path the OS allows.

## Non-goals

- No change to `ClaudeRunner` behavior. The Claude path through `harness.generate_mcp_config()` already rewrites `cwd` per-run; that contract stays as-is.
- No code-only enforcement for Codex (that's Slice 5).
- No change to the on-disk shape of the Codex `config.toml` produced per run (Codex consumers already accept the current schema).
- Not introducing a new TOML dependency unless stdlib `tomllib` + a hand-rolled writer is insufficient. (Python 3.11 has `tomllib` for reading only.)

## Design

### 1. CLI: `swebench mcp-config generate`

New subcommand in [swebench/cli.py](../../swebench/cli.py), implemented in a new `swebench/mcp_cli.py` module (mirrors the pattern of `swebench/cache_cli.py`).

```
swebench mcp-config generate [--out PATH]
```

Behavior:
- Resolves `node` via `shutil.which("node")`; falls back to `/usr/bin/node` if present; else exits non-zero with a clear message.
- Resolves bundle path: `Path(swebench.__file__).parent.parent / "exec_server/dist/exec-server.bundle.mjs"`. If the file does not exist, exits non-zero pointing at `npm run build` in `exec_server/`.
- Resolves `cwd` to the package root (same parent as the bundle).
- Writes the JSON to `--out` (default: `mcp-config.json` at the repo root).
- Preserves any non-`codebox` MCP servers if the target file already exists (read-merge-write); a brand-new write produces only the `codebox` entry.

Output schema is identical to the current [mcp-config.json](../../mcp-config.json) — see the existing file for the canonical shape.

### 2. Pre-flight in `CodexRunner`

Add a public method on `CodexRunner`:

```python
def preflight(self, mcp_config_path: str | None) -> None:
    """Raise RuntimeError with an actionable message if Codex cannot run."""
```

Called by `artifact_run.py` / `run.py` before the first Codex arm, paralleling the existing pre-flight pattern used for Claude.

Checks (all raise `RuntimeError` on failure with a message naming the missing thing and the fix):
- `find_binary()` resolves a Codex binary (existing behavior; just surface its `FileNotFoundError` as `RuntimeError`).
- `_resolve_bundle(mcp_config_path)` returns a path that exists.
- `shutil.which("node")` is non-`None`, OR `/usr/bin/node` is executable.

`_resolve_bundle()` keeps its current fallback-to-package-relative behavior — pre-flight just makes the failure loud and early when *all* resolution paths fail.

### 3. TOML path-safety in `_write_codex_config`

Replace the f-string with a small helper that escapes TOML basic-string contents:

```python
def _toml_str(s: str) -> str:
    # TOML basic strings: backslash and double-quote require escaping;
    # control chars are forbidden but won't appear in filesystem paths.
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
```

Use `_toml_str(bundle_path)`, `_toml_str(cwd)`, and `_toml_str(persistent_kernel)` at the three interpolation sites in `_write_codex_config()`. Do not introduce a third-party TOML library.

## File ownership

| File | Change |
|---|---|
| `swebench/runner.py` | Add `CodexRunner.preflight()`; refactor `_write_codex_config()` to use `_toml_str()` helper |
| `swebench/mcp_cli.py` | **New** — `mcp-config generate` Click subcommand |
| `swebench/cli.py` | Wire the new `mcp-config` group into the root CLI |
| `swebench/run.py` | Call `runner.preflight(mcp_config_path)` before the first Codex arm |
| `swebench/artifact_run.py` | Same — call `runner.preflight()` before the first Codex arm |
| `mcp-config.json` | Document in a top-of-file comment that this file is regenerable via `swebench mcp-config generate` (NB: JSON has no comments; instead, add a note in [README.md](../../README.md)) |
| `tests/test_runner.py` | Add tests for `_toml_str`, `preflight` success + each failure mode |
| `tests/test_mcp_cli.py` | **New** — tests for the generate subcommand: fresh write, merge-preserve, missing-bundle exit code |
| `README.md` | Brief mention of `swebench mcp-config generate` in the setup section |

Files NOT to touch: `harness.py` (`generate_mcp_config` for Claude stays as-is), `artifact_models.py`, `cache*.py`.

## Acceptance criteria

- [ ] `swebench mcp-config generate` writes a `mcp-config.json` with the current environment's `node` path, package-relative bundle path, and package-root `cwd`.
- [ ] `swebench mcp-config generate --out /tmp/x.json` against an existing file with a non-`codebox` MCP server preserves that server.
- [ ] `swebench mcp-config generate` exits non-zero with a clear message when the bundle does not exist (suggesting `npm run build`).
- [ ] Starting a Codex arm when the bundle is missing raises `RuntimeError` before `subprocess.run(codex ...)` is called, with the path and the build instruction in the message.
- [ ] `_write_codex_config` produces valid TOML for paths containing `"` and `\`. Verified by round-trip parse with `tomllib.loads()` in a test.
- [ ] All existing tests in [tests/test_runner.py](../../tests/test_runner.py) still pass unchanged.
- [ ] New tests cover: `_toml_str` escaping, `preflight` success path, `preflight` failure per missing component, `mcp-config generate` fresh + merge-preserve + missing-bundle.

## Out of scope / explicit deferrals

- Auto-detecting the bundle from a built `package.json` — the package-relative path is sufficient given the repo layout.
- Replacing the hand-rolled TOML writer with a library — revisit if a fourth interpolation site appears.
- Validating that the `node` binary is a version Codex MCP accepts — Codex itself will surface that mismatch.

## Test plan

1. Unit: `tests/test_runner.py::test_write_codex_config_escapes_special_chars` — write a config with `bundle_path = '/tmp/has "quote"/bundle.mjs'` and `cwd = r'C:\Windows\path'`; parse the result with `tomllib.loads()` and assert the round-trip preserves the strings.
2. Unit: `tests/test_runner.py::test_codex_preflight_missing_bundle` — monkeypatch `_resolve_bundle` to raise; assert `preflight` raises `RuntimeError` with `npm run build` in the message.
3. Unit: `tests/test_runner.py::test_codex_preflight_missing_node` — monkeypatch `shutil.which("node")` to `None` and `/usr/bin/node` missing; assert clear error.
4. Unit: `tests/test_runner.py::test_codex_preflight_happy_path` — point at a real bundle file in a tmp dir; assert no raise.
5. CLI: `tests/test_mcp_cli.py::test_generate_fresh_write` — run the subcommand against a tmp dir with a fake bundle; assert resulting JSON has resolved paths.
6. CLI: `tests/test_mcp_cli.py::test_generate_preserves_other_servers` — pre-populate target file with a non-`codebox` server; run generate; assert the other server is preserved.
7. CLI: `tests/test_mcp_cli.py::test_generate_exits_when_bundle_missing` — assert non-zero exit and helpful stderr.
8. Manual smoke: in the dev container, run `swebench mcp-config generate --out /tmp/regen.json` and diff against the checked-in `mcp-config.json` — only `command` (if `node` is at a different path) should differ.
