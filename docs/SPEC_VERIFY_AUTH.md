# SPEC — `AgentRunner.verify_auth()` and `make_isolated_config` privatization

**Status**: proposed for PR #225 follow-up
**Resolves**: F-1 (major), F-2 (minor), F-3 (minor), F-6 (minor) from review-fix-proposals on PR #225
**Scope**: `swebench/runner.py`, `swebench/run.py`, `swebench/artifact_cli.py`, `tests/test_runner.py`. No behavior change for `claude_code` arms. No new functional capability — pure refactor of the preflight contract.

---

## Problem

PR #225 introduced a Codex-specific preflight in `run_command`:

```python
runner = make_runner(agent_surface)
claude_binary = runner.find_binary()
if agent_surface == "codex_cli":
    runner.make_isolated_config()  # verify auth early; discard result
```

This is wrong for three reasons:

1. **Bundle-required-for-baseline (F-1, major).** `make_isolated_config` does two unrelated jobs: (a) check & copy `~/.codex/auth.json`, (b) write `config.toml` referencing `exec_server/dist/exec-server.bundle.mjs`. The bundle is gitignored and only needed for `onlycode`/`code_only` arms, yet preflight requires it for every `codex_cli` invocation including `--arms baseline`. AC1 of #224 is broken on a clean checkout.
2. **Leaked temp dir (F-2, minor).** `make_isolated_config` returns a `tempfile.mkdtemp` path. The preflight discards it without `shutil.rmtree`, leaking a `/tmp/codex-eval-*` dir containing a copy of `auth.json` on every run.
3. **Surface branching leaks past the abstraction (F-3, F-6).** The `if agent_surface == "codex_cli":` branch defeats the `AgentRunner` ABC. `artifact_cli.py` has no equivalent preflight (F-3). The local `claude_binary` variable name lies once it might hold a `codex` path (F-6).

The module docstring at `swebench/runner.py:19-20` explicitly states:

> Config/auth isolation is handled *internally* by each runner's invoke() method — callers do not manage temp dirs directly.

Exposing `make_isolated_config` to callers violates that contract.

## Goals

- Preflight checks **auth only** — never the exec-server bundle.
- Preflight is **surface-agnostic** — no `if agent_surface == "codex_cli"` branch in callers.
- Preflight has **no side effects on disk** — no temp dirs created.
- `make_isolated_config` returns to being a private helper of `invoke()`, restoring the module contract.

## Non-goals

- No change to `ClaudeRunner` runtime behavior. The `claude_code` arm stays byte-for-byte identical.
- No change to the `codex_cli + onlycode` rejection guard (Slice 5 territory).
- No change to the analyze-pipeline guard (`_check_not_codex_jsonl`).
- No change to `config.toml` contents or exec-server bundle resolution.

## Design

### New ABC method

```python
class AgentRunner(ABC):
    @abstractmethod
    def verify_auth(self) -> None:
        """Raise FileNotFoundError if required auth artifacts are missing.

        Called by preflight code. Must have no side effects (no temp dirs,
        no file copies). A no-op return means auth is plausibly valid; it
        does not guarantee a live session.
        """
```

### ClaudeRunner implementation

```python
def verify_auth(self) -> None:
    return  # claude validates credentials inside invoke()
```

A no-op. ClaudeRunner already copies `~/.claude/.credentials.json` and `~/.claude/.claude.json` inside `invoke()` and tolerates either being absent (the `claude` binary then fails its own login check). There is no surface-level pre-check today; adding one here would change ClaudeRunner behavior and is out of scope.

### CodexRunner implementation

```python
def verify_auth(self) -> None:
    src = os.path.expanduser("~/.codex/auth.json")
    if not os.path.isfile(src):
        raise FileNotFoundError(
            "~/.codex/auth.json not found — Codex CLI requires a valid auth token."
        )
```

Pure check. Same error string as before (callers and tests that pattern-match on `~/.codex/auth.json` keep working).

### `make_isolated_config` becomes private

Rename `CodexRunner.make_isolated_config` → `CodexRunner._make_isolated_config`. The auth check inside it is kept (defense in depth: anyone bypassing preflight still gets a clear error). Only `invoke()` calls it.

### Preflight call sites

`swebench/run.py`:

```python
try:
    runner = make_runner(agent_surface)
    agent_binary = runner.find_binary()
    runner.verify_auth()
except (ValueError, FileNotFoundError) as e:
    click.echo(f"ERROR: {e}", err=True)
    raise SystemExit(1)
```

`swebench/artifact_cli.py` (currently has no auth preflight at all — F-3):

```python
try:
    runner = make_runner(agent_surface)
    binary = runner.find_binary()
    runner.verify_auth()
except (ValueError, FileNotFoundError) as exc:
    click.echo(f"ERROR: {exc}", err=True)
    raise SystemExit(1)
```

### Rename freebie (F-6)

In `swebench/run.py`, the local `claude_binary` variable now genuinely holds either a `claude` or `codex` path. Rename to `agent_binary` for the four occurrences in `run_command` (lines 621, 712, 874, 928) and the matching keyword in the `_run_arm` callsites. The `_run_arm` parameter name (`claude_binary: str` at line 142) also gets renamed; all internal uses (lines 266, 274, 284) follow.

## Test changes

| Old test | Replacement |
|---|---|
| `test_codex_make_isolated_config_missing_auth` | `test_codex_verify_auth_raises_when_auth_missing` — same monkeypatch, calls `verify_auth()`. |
| `test_codex_make_isolated_config_success` | Keep but rename `make_isolated_config` → `_make_isolated_config` to test the internal helper still works. Justified because `_resolve_bundle` behavior matters for `invoke()`. |
| `test_run_command_rejects_codex_onlycode` | Update monkeypatch from `swebench.runner.CodexRunner.make_isolated_config` to `swebench.runner.CodexRunner.verify_auth`. |
| (new) | `test_claude_verify_auth_is_noop` — instantiate `ClaudeRunner()`, call `verify_auth()`, assert it returns `None` and doesn't raise. |
| (new) | `test_run_command_codex_baseline_succeeds_without_exec_server_bundle` — stubs `find_binary` and `verify_auth`, monkeypatches `_resolve_bundle` to raise, asserts `run_command` reaches the arm-execution stage without the bundle. |

The analyze-guard test (`test_codex_jsonl_analyze_guard`) is unaffected.

## Acceptance criteria

| # | Criterion | How verified |
|---|---|---|
| AC1 | `swebench run --agent-surface codex_cli --arms baseline` does not require `exec_server/dist/exec-server.bundle.mjs` to exist at preflight time | `test_run_command_codex_baseline_succeeds_without_exec_server_bundle` |
| AC2 | Preflight creates zero temp dirs on success | Implementation review: `verify_auth` has no `mkdtemp` call |
| AC3 | `run_command` and `artifact_run_command` use identical preflight code (no surface-specific branching) | Implementation review: both call `runner.verify_auth()` |
| AC4 | `CodexRunner.verify_auth()` raises `FileNotFoundError` containing `"~/.codex/auth.json"` when auth absent | `test_codex_verify_auth_raises_when_auth_missing` |
| AC5 | `ClaudeRunner.verify_auth()` is a no-op | `test_claude_verify_auth_is_noop` |
| AC6 | `CodexRunner.make_isolated_config` is no longer part of the public API (only `_make_isolated_config` remains) | `grep -n "\.make_isolated_config" swebench/ tests/` returns no matches outside `runner.py` |
| AC7 | All previously passing tests still pass | `pytest -m "not integration"` |
| AC8 | `claude_code` arm behavior is byte-for-byte unchanged | `ClaudeRunner.invoke` body is untouched (diff review) |

## Risks

- **Test rename churn.** Three tests are renamed or repointed. Test descriptions are updated to match.
- **Defense-in-depth concern.** Removing the auth check from preflight does not remove it from `_make_isolated_config` — it stays there for runs that bypass preflight (none today, but cheap insurance).
- **Future Slice 5.** When `codex_cli + onlycode` lands, the bundle requirement returns at run time inside `invoke()`. A future preflight may want to check the bundle conditionally (only when `onlycode` is in arm_list). Out of scope here.

## Rollout

Single commit on `fix/issue-224-codex-cli-arm-e2e`. Pushed to PR #225. No migration needed — no external callers of `make_isolated_config` exist (verified by grep).
