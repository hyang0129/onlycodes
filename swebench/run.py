"""Process 2: run — execute baseline and/or onlycode arms on SWE-bench instances."""

from __future__ import annotations

import io
import json
import os
import random
import re
import shutil
import time
import traceback
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from pathlib import Path
from typing import NamedTuple

import click

from swebench import repo_root
from swebench.cache import (
    Backend,
    cache_paths,
    detect_overlay_backend,
    has_cached_instance,
    mount_overlay,
    reinstall_editable,
    scrub_cache_dir,
    unmount_overlay,
    verify_lockfile,
    write_lockfile,
    OverlayError,
)
from swebench.harness import (
    apply_test_patch,
    clone_repo,
    find_claude_binary,
    get_claude_version,
    git_reset,
    run_claude,
    run_tests,
    setup_venv,
    strip_git_history,
)
from swebench.models import Problem


def _mcp_config_without_persistent_kernel(
    base_path: str,
    results_dir: str | os.PathLike,
    instance_id: str,
    run_idx: int,
) -> str:
    """Return a tempfile path to a copy of ``base_path`` with the
    ``ONLYCODES_PERSISTENT_KERNEL`` env var removed from every server entry.

    Written under ``results_dir`` so it shares the run's lifetime and is
    easy to inspect after the fact. Same (instance, run) always maps to the
    same filename, so re-runs overwrite cleanly.
    """
    with open(base_path) as f:
        cfg = json.load(f)
    for srv in cfg.get("mcpServers", {}).values():
        env = srv.get("env")
        if isinstance(env, dict):
            env.pop("ONLYCODES_PERSISTENT_KERNEL", None)
            if not env:
                srv.pop("env", None)
    out_path = os.path.join(
        str(results_dir), f"_mcp-config_{instance_id}_run{run_idx}_nokernel.json"
    )
    with open(out_path, "w") as f:
        json.dump(cfg, f, indent=2)
    return out_path


class _ArmTask(NamedTuple):
    """Describes one arm execution to schedule."""

    problem: Problem
    arm: str
    run_idx: int
    repo_dir: str
    venv_dir: str
    needs_editable_reinstall: bool = False


def _is_triple_complete(
    results_dir: str | os.PathLike,
    instance_id: str,
    arm: str,
    run_idx: int,
) -> str | None:
    """Return the recorded verdict if a (instance_id, arm, run_idx) triple is
    already complete, else ``None``.

    A triple is considered complete iff:

    - ``<results_dir>/<instance_id>_<arm>_run<N>.jsonl`` exists, AND
    - ``<results_dir>/<instance_id>_<arm>_run<N>_test.txt`` exists, AND
    - the test file's last non-empty line (stripped of trailing whitespace) is
      exactly ``PASS`` or ``FAIL``.

    If any of those conditions fail (missing file, no verdict, empty file,
    mid-run kill leaving partial output), the triple is **incomplete** and the
    caller must re-run it. Returning ``None`` signals "re-run"; returning the
    verdict string signals "skip".
    """
    results_dir = str(results_dir)
    jsonl_path = os.path.join(results_dir, f"{instance_id}_{arm}_run{run_idx}.jsonl")
    test_path = os.path.join(results_dir, f"{instance_id}_{arm}_run{run_idx}_test.txt")

    if not os.path.isfile(jsonl_path) or not os.path.isfile(test_path):
        return None

    try:
        with open(test_path) as f:
            lines = f.readlines()
    except OSError:
        return None

    # Walk backward for the last non-empty (stripped) line.
    for raw in reversed(lines):
        line = raw.strip()
        if not line:
            continue
        if line == "PASS" or line == "FAIL":
            return line
        return None

    # File was empty or whitespace-only.
    return None


def _run_arm(
    *,
    problem: Problem,
    arm: str,
    run_idx: int,
    repo_dir: str,
    venv_dir: str,
    results_dir: str,
    claude_binary: str,
    mcp_config_path: str,
    root: Path,
    persistent_kernel: bool = True,
    log_buffer: io.StringIO | None = None,
    needs_editable_reinstall: bool = False,
) -> str:
    """Run a single arm (baseline or onlycode) for one instance.

    Returns the verdict string ("PASS", "FAIL", or "ERROR").
    When *log_buffer* is provided, all output is written there instead of
    directly to stdout so that parallel runs don't interleave.

    When *needs_editable_reinstall* is True, ``reinstall_editable`` is run
    after ``git_reset`` to regenerate the ``.egg-info`` directory that
    ``git clean -fd`` removes. This is required for the cached/overlay path
    because the egg-info is untracked by git and would otherwise disappear
    between arm runs.
    """

    def _echo(msg: str) -> None:
        if log_buffer is not None:
            log_buffer.write(msg + "\n")
        else:
            click.echo(msg)

    _echo(f"  [{arm} run {run_idx}] Starting...")

    # Reset repo to its current HEAD rather than ``problem.base_commit``: the
    # history-strip routine (see ``strip_git_history``) has already collapsed
    # the repo to a single orphan commit whose tree matches ``base_commit``
    # but whose SHA differs. ``git_reset(repo_dir, "HEAD")`` gives us the same
    # "discard agent edits, clean untracked" semantics without needing the
    # original SHA that no longer exists in the object graph.
    git_reset(repo_dir, "HEAD")

    # The git_reset above runs `git clean -fd`, which wipes the untracked
    # .egg-info/ directory that reinstall_editable placed in the overlay
    # upperdir. For cached/overlay runs, regenerate it here so editable
    # imports (entry_points, console scripts) keep working.
    if needs_editable_reinstall:
        reinstall_editable(venv_dir, repo_dir)

    # Apply test patch
    if problem.patch_file:
        patch_path = str(root / problem.patch_file)
        if apply_test_patch(repo_dir, patch_path):
            _echo(f"  [{arm} run {run_idx}] Applied test patch.")
        else:
            _echo(f"  [{arm} run {run_idx}] WARNING: test patch failed to apply.")

    # Build prompt from problem_statement — eliminates hardcoded text bug
    venv_python = os.path.join(venv_dir, "bin", "python")
    is_onlycode = arm == "onlycode"
    prompt_parts = [
        f"You are working in the repository at: {repo_dir}\n",
        f"The project's Python interpreter and dependencies are pre-installed at: {venv_python}",
        f"Use this interpreter to run tests (e.g. `{venv_python} tests/runtests.py ...`).\n",
    ]
    if is_onlycode:
        prompt_parts.append(
            "A `codebox` helper module is auto-imported into your cwd. Prefer it "
            "over hand-rolled subprocess.run(['cat', ...]) — its output is "
            "byte-stable across identical reads, which keeps prompt-cache reuse "
            "high. API:\n"
            "  import codebox\n"
            "  src   = codebox.read(path)              # full file as string\n"
            "  block = codebox.read_lines(path, 200, 250)  # inclusive 1-indexed\n"
            "  hits  = codebox.grep('pattern', path)   # 'path:line:text', sorted\n"
            "  paths = codebox.files(root, pattern=None)   # recursive, sorted\n"
            "  codebox.edit_replace(path, old, new)    # exact-once literal string, raises if 0/many\n"
            "  codebox.write(path, content)            # overwrite whole file, mkdir -p\n"
            "\n"
            "To modify a file, use `codebox.edit_replace(path, old, new)` (an "
            "exact-literal string swap — think of it as the Write tool's sibling "
            "for surgical edits) or `codebox.write(path, content)` to rewrite the "
            "whole file. Do NOT build edits by hand with `re.sub`, regex "
            "substitution, string-split-and-join, or writing a script that "
            "reads/mutates/writes a file — those patterns silently corrupt files "
            "on partial matches. `edit_replace` raises on 0 or >1 matches, which "
            "is the safety you want.\n"
        )
        if persistent_kernel:
            prompt_parts.append(
                "The execute_code Python interpreter is a PERSISTENT REPL keyed by cwd: "
                "variables, imports, and opened-file contents survive across calls. "
                "After you read a file once with `src = codebox.read(path)`, reference "
                "`src` on later turns instead of re-reading. Re-reading a file you "
                "already loaded wastes tokens — before issuing any read, check what "
                "you already have in memory.\n"
            )
    prompt_parts.append(
        f"Fix the following bug. Make the minimal change needed.\n\n"
        f"{problem.problem_statement}"
    )
    prompt = "\n".join(prompt_parts)

    result_file = os.path.join(results_dir, f"{problem.instance_id}_{arm}_run{run_idx}.jsonl")

    # Build tools flags based on arm
    tools_flags: list[str] = []
    if is_onlycode:
        # --tools whitelists MCP tools but does not reliably block built-ins
        # like Monitor (added v2.1.98). --disallowedTools explicitly removes
        # every built-in so the agent can only use the two codebox MCP tools.
        _BLOCKED_BUILTINS = (
            "Agent,AskUserQuestion,Bash,CronCreate,CronDelete,CronList,"
            "Edit,EnterPlanMode,EnterWorktree,ExitPlanMode,ExitWorktree,"
            "Glob,Grep,ListMcpResourcesTool,LSP,Monitor,NotebookEdit,"
            "PowerShell,PushNotification,Read,ReadMcpResourceTool,"
            "RemoteTrigger,SendMessage,Skill,"
            "TaskCreate,TaskGet,TaskList,TaskOutput,TaskStop,TaskUpdate,"
            "TeamCreate,TeamDelete,TodoWrite,ToolSearch,WebFetch,WebSearch,Write"
        )
        # The default mcp-config.json enables the persistent kernel via
        # ONLYCODES_PERSISTENT_KERNEL=1. When --no-persistent-kernel is passed
        # we emit a per-run temp config with that env scrubbed.
        effective_mcp_config = mcp_config_path
        if not persistent_kernel:
            effective_mcp_config = _mcp_config_without_persistent_kernel(
                mcp_config_path, results_dir, problem.instance_id, run_idx
            )
        tools_flags = [
            "--mcp-config", effective_mcp_config,
            "--strict-mcp-config",
            "--tools", "mcp__codebox__execute_code,mcp__codebox__list_tools",
            "--disallowedTools", _BLOCKED_BUILTINS,
        ]

    start_time = time.time()

    # Prepend a metadata record so every JSONL is self-describing.
    claude_version = get_claude_version(claude_binary)
    with open(result_file, "w") as _meta_f:
        _meta_f.write(json.dumps({
            "type": "meta",
            "instance_id": problem.instance_id,
            "arm": arm,
            "run": run_idx,
            "claude_binary": claude_binary,
            "claude_version": claude_version,
        }) + "\n")

    run_claude(
        prompt=prompt,
        repo_dir=repo_dir,
        system_prompt="You are a helpful assistant.",
        tools_flags=tools_flags,
        result_file=result_file,
        claude_binary=claude_binary,
    )

    wall_secs = int(time.time() - start_time)

    # Run tests
    test_result_file = os.path.join(
        results_dir, f"{problem.instance_id}_{arm}_run{run_idx}_test.txt"
    )

    _echo(f"  [{arm} run {run_idx}] Running test suite...")

    verdict = run_tests(
        repo_dir=repo_dir,
        test_cmd=problem.test_cmd,
        venv_dir=venv_dir,
        result_file=test_result_file,
    )

    _echo(f"  [{arm} run {run_idx}] Tests: {verdict} ({wall_secs}s wall)")

    # Extract cost and turns from stream-json output
    cost = "N/A"
    turns = "N/A"
    try:
        with open(result_file) as f:
            content = f.read()
        cost_matches = re.findall(r'"total_cost_usd":\s*([\d.]+)', content)
        turns_matches = re.findall(r'"num_turns":\s*(\d+)', content)
        if cost_matches:
            cost = f"${cost_matches[-1]}"
        if turns_matches:
            turns = turns_matches[-1]
    except (OSError, ValueError):
        pass

    _echo(f"  [{arm} run {run_idx}] Cost: {cost}, Turns: {turns}, Wall: {wall_secs}s")
    return verdict


def _setup_problem(problem: Problem, clone_base: str) -> tuple[str, str]:
    """Clone repo and set up venv for a single problem. Returns (repo_dir, venv_dir).

    This is the default (non-cache) path and matches pre-caching behaviour.
    """
    repo_dir = os.path.join(clone_base, problem.instance_id)
    venv_dir = os.path.join(clone_base, "venvs", problem.instance_id)
    # Always wipe the repo dir before cloning: a prior stripped run leaves only
    # the orphan commit, so git_reset to base_commit would fail on reuse.
    shutil.rmtree(repo_dir, ignore_errors=True)
    clone_repo(problem.repo_slug, repo_dir)
    git_reset(repo_dir, problem.base_commit)
    # Strip history so the agent cannot recover the upstream fix via git log.
    # Safe to do here: this clone is thrown away after the run.
    strip_git_history(repo_dir)
    setup_venv(venv_dir, repo_dir)
    return repo_dir, venv_dir


class _OverlayHandle(NamedTuple):
    """Records the directories an overlay mount allocated, for teardown."""

    merged: str
    upperdir: str
    workdir: str
    backend: Backend
    lowerdir: str = ""  # set for cached overlays so they can be refreshed between arms


def _setup_problem_cached(
    problem: Problem,
    *,
    run_tag: str,
    overlay_tmp_root: str,
    overlay_backend: Backend,
) -> tuple[str, str, _OverlayHandle | None]:
    """Cache-aware per-problem setup.

    Returns ``(repo_dir, venv_dir, overlay_handle)``. ``overlay_handle`` is
    ``None`` when the instance isn't cached (caller falls back to the plain
    ``_setup_problem`` path).

    On a cached instance, mounts an overlay whose lowerdir is the cached
    ``repo/``, verifies the venv's pip-freeze matches the captured lockfile
    (rebuilding the cache entry if it drifted), and re-runs ``pip install -e``
    so ``.egg-info`` exists in the overlay.
    """
    if not has_cached_instance(problem.instance_id):
        return ("", "", None)

    paths = cache_paths(problem.instance_id)
    lower = paths["repo"]
    venv_dir = paths["venv"]
    lockfile = paths["lockfile"]

    # Venv integrity — if Claude leaked a pip install into a prior run, rebuild.
    if not verify_lockfile(venv_dir, lockfile):
        click.echo(
            f"  {problem.instance_id}: venv lockfile mismatch — rebuilding cache entry."
        )
        # Rebuild means: scrub any mutations the venv picked up. We can't
        # un-pip-install without knowing what was added, so the safest path is
        # to recreate the venv from scratch.
        # First, reset the lowerdir to base_commit so it is clean before
        # rebuilding — a prior run may have left the lowerdir in a modified
        # state (e.g. partial edits, stale .egg-info from a previous
        # setup_venv call that scrub_cache_dir later removed).
        git_reset(lower, problem.base_commit)
        shutil.rmtree(venv_dir, ignore_errors=True)
        setup_venv(venv_dir, lower)
        scrub_cache_dir(lower)
        write_lockfile(venv_dir, lockfile)

    # Allocate overlay dirs unique to this (problem, run_tag) pair.
    overlay_root = os.path.join(overlay_tmp_root, f"{problem.instance_id}-{run_tag}")
    upperdir = os.path.join(overlay_root, "upper")
    workdir = os.path.join(overlay_root, "work")
    merged = os.path.join(overlay_root, "merged")
    for d in (upperdir, workdir, merged):
        os.makedirs(d, exist_ok=True)

    mount_overlay(lower, upperdir, workdir, merged, overlay_backend)

    # Strip git history in the merged overlay view. Writes materialise into
    # the upperdir only — the cached lowerdir (``repo/``) and the shared bare
    # repo remain untouched. Without this, an agent could run ``git log`` /
    # ``git show`` against the overlay and read the upstream reference fix
    # through the alternates link to the bare repo.
    strip_git_history(merged)

    return (
        merged,
        venv_dir,
        _OverlayHandle(
            merged=merged,
            upperdir=upperdir,
            workdir=workdir,
            backend=overlay_backend,
            lowerdir=lower,
        ),
    )


def _teardown_overlay(handle: _OverlayHandle) -> None:
    """Unmount and rm -rf the overlay's upper/work/merged directories."""
    try:
        unmount_overlay(handle.merged, handle.backend)
    except Exception:  # noqa: BLE001 — teardown must not raise
        pass
    for d in (handle.upperdir, handle.workdir, handle.merged):
        shutil.rmtree(d, ignore_errors=True)
    # Remove the common parent if now empty.
    parent = os.path.dirname(handle.merged)
    try:
        os.rmdir(parent)
    except OSError:
        pass


def _refresh_overlay(handle: _OverlayHandle, venv_dir: str) -> _OverlayHandle:
    """Reset a cached overlay to a clean state for the next arm.

    fuse-overlayfs copy-up makes files written by arm N unresettable via
    ``git reset --hard`` (EEXIST on the upperdir entry). Refreshing the overlay
    — unmount, delete upper+work, recreate, remount — gives the next arm a
    pristine view of the cached lowerdir without touching it.

    Returns the same handle (paths unchanged); the mount is fresh.
    """
    unmount_overlay(handle.merged, handle.backend)
    shutil.rmtree(handle.upperdir, ignore_errors=True)
    shutil.rmtree(handle.workdir, ignore_errors=True)
    os.makedirs(handle.upperdir, exist_ok=True)
    os.makedirs(handle.workdir, exist_ok=True)
    mount_overlay(handle.lowerdir, handle.upperdir, handle.workdir, handle.merged, handle.backend)
    # Between-arm refresh wiped the upperdir, so the merged view now exposes
    # the full history from the lowerdir again. Re-strip so the next arm
    # starts from a single-orphan-commit view.
    strip_git_history(handle.merged)
    return handle


# Global lock for serialised stdout flushing.
_print_lock = threading.Lock()


def _flush_buffer(header: str, buf: io.StringIO) -> None:
    """Write buffered output to stdout atomically under a lock."""
    text = buf.getvalue()
    with _print_lock:
        click.echo(header)
        if text:
            click.echo(text, nl=False)
        click.echo()


def _cleanup_stale_overlays(
    problems: list[Problem], overlay_tmp_root: str, backend: "Backend"
) -> None:
    """Unmount and remove leftover overlay dirs from a previously interrupted run."""
    instance_ids = {p.instance_id for p in problems}
    try:
        entries = os.listdir(overlay_tmp_root)
    except OSError:
        return
    for entry in entries:
        # Match any dir named "{instance_id}-*" (e.g. "-eval", "-baseline-1-eval")
        for iid in instance_ids:
            if entry.startswith(f"{iid}-"):
                overlay_root = os.path.join(overlay_tmp_root, entry)
                if not os.path.isdir(overlay_root):
                    break
                merged = os.path.join(overlay_root, "merged")
                # Only remove dirs that look like overlay roots — skip any
                # unrelated tool that creates /tmp/{iid}-something for other
                # reasons (F-9: verify overlay structure before deleting).
                if not os.path.isdir(merged):
                    break
                try:
                    unmount_overlay(merged, backend)
                except Exception:
                    pass
                shutil.rmtree(overlay_root, ignore_errors=True)
                click.echo(f"  cleaned stale overlay: {overlay_root}")
                break


@click.command("run")
@click.option(
    "--filter",
    "filter_ids",
    default=None,
    help="Comma-separated instance IDs to run (default: all in problems/).",
)
@click.option(
    "--arms",
    type=click.Choice(["baseline", "onlycode", "both"]),
    default="both",
    help="Which arms to run (default: both).",
)
@click.option(
    "--persistent-kernel/--no-persistent-kernel",
    "persistent_kernel",
    default=True,
    show_default=True,
    help=(
        "For the onlycode arm, run the execute_code Python interpreter as a "
        "persistent REPL (variables/imports survive across calls). Default on. "
        "Pass --no-persistent-kernel to run every call in a fresh subprocess."
    ),
)
@click.option(
    "--runs",
    "num_runs",
    type=int,
    default=1,
    help="Number of runs per arm (default: 1).",
)
@click.option(
    "--parallel",
    "parallel",
    type=int,
    default=1,
    help="Max problems to run concurrently (default: 1 = serial).",
)
@click.option(
    "--fail-fast",
    "fail_fast",
    is_flag=True,
    default=False,
    help="Stop on first FAIL verdict. Cancels queued tasks; already-running Claude invocations finish.",
)
@click.option(
    "--use-cache/--no-cache",
    "use_cache",
    default=True,
    show_default=True,
    help=(
        "Use the OverlayFS-backed instance cache when available (default: on). "
        "Requires `python -m swebench cache setup` to have been run first. Falls back "
        "to the default clone+venv path for any instance that isn't cached. "
        "Pass --no-cache to opt out."
    ),
)
@click.option(
    "--shuffle-arms/--no-shuffle-arms",
    "shuffle_arms",
    default=True,
    show_default=True,
    help="Randomize arm execution order per problem per run (default: on). Disable to always run baseline before onlycode.",
)
@click.option(
    "--output-dir",
    "output_dir",
    type=click.Path(file_okay=False, dir_okay=True, resolve_path=False),
    default=None,
    help="Directory for result files [default: <repo>/results_swebench/]. Created if it does not exist.",
)
@click.option(
    "--resume/--no-resume",
    "resume",
    default=True,
    show_default=True,
    help=(
        "Skip (instance, arm, run) triples that already have a completed "
        "result in --output-dir. A triple is complete when both its .jsonl "
        "and _test.txt exist and the test file's last non-empty line is "
        "PASS or FAIL; otherwise it is re-run."
    ),
)
def run_command(
    filter_ids: str | None,
    arms: str,
    persistent_kernel: bool,
    num_runs: int,
    parallel: int,
    fail_fast: bool,
    use_cache: bool,
    shuffle_arms: bool,
    output_dir: str | None,
    resume: bool,
) -> None:
    """Run SWE-bench evaluation arms on problem instances."""
    if parallel < 1:
        click.echo("ERROR: --parallel must be >= 1", err=True)
        raise SystemExit(1)

    root = repo_root()
    problems_dir = root / "problems"
    results_dir = Path(output_dir) if output_dir else root / "results_swebench"
    mcp_config_path = str(root / "mcp-config.json")
    clone_base = "/tmp/swebench"

    results_dir.mkdir(parents=True, exist_ok=True)
    os.makedirs(clone_base, exist_ok=True)

    # Find claude binary
    try:
        claude_binary = find_claude_binary()
    except FileNotFoundError as e:
        click.echo(f"ERROR: {e}", err=True)
        raise SystemExit(1)

    # Load problems (recurse into subfolders so curated sets in e.g.
    # problems/swebench-verified-mini/ and problems/adhoc/ are all picked up).
    yaml_files = sorted(problems_dir.rglob("*.yaml"))
    if not yaml_files:
        click.echo("ERROR: No problem files found in problems/. Run 'python -m swebench add' first.", err=True)
        raise SystemExit(1)

    problems = [Problem.from_yaml(f) for f in yaml_files]

    # Apply filter
    if filter_ids:
        ids = {s.strip() for s in filter_ids.split(",")}
        problems = [p for p in problems if p.instance_id in ids]
        if not problems:
            click.echo(f"ERROR: No matching problems for filter: {filter_ids}", err=True)
            raise SystemExit(1)

    # Determine arms to run
    arm_list: list[str] = []
    if arms in ("baseline", "both"):
        arm_list.append("baseline")
    if arms in ("onlycode", "both"):
        arm_list.append("onlycode")

    # --- Environment pre-flight checks ------------------------------------------
    env_errors: list[str] = []
    if "onlycode" in arm_list:
        _configs_to_check = [mcp_config_path]
        for _cfg in _configs_to_check:
            if not os.path.isfile(_cfg):
                env_errors.append(f"MCP config not found at {_cfg}")
                continue
            try:
                with open(_cfg) as _f:
                    _mcp = json.load(_f)
                for _srv_name, _srv in _mcp.get("mcpServers", {}).items():
                    _cmd = _srv.get("command", "")
                    if _cmd and not (os.path.isfile(_cmd) and os.access(_cmd, os.X_OK)):
                        if not shutil.which(_cmd):
                            env_errors.append(
                                f"MCP server '{_srv_name}' command not found or not executable: {_cmd!r}"
                            )
                    _args = _srv.get("args", [])
                    for _arg in _args:
                        if _arg.endswith((".mjs", ".js", ".cjs")) and not os.path.isfile(_arg):
                            env_errors.append(
                                f"MCP server '{_srv_name}' script not found: {_arg!r}"
                            )
            except (json.JSONDecodeError, OSError) as _e:
                env_errors.append(f"Failed to parse {_cfg}: {_e}")

    if env_errors:
        click.echo("ERROR: Environment pre-flight failed:", err=True)
        for _err in env_errors:
            click.echo(f"  • {_err}", err=True)
        click.echo(
            "\nFix the issues above before running the onlycode arm.\n"
            "  - Node.js must be installed for exec-server.bundle.mjs\n"
            "  - Install with: sudo apt-get install -y nodejs",
            err=True,
        )
        raise SystemExit(1)

    click.echo(f"=== SWE-bench Evaluation ===")
    click.echo(f"Problems: {len(problems)}")
    click.echo(f"Arms: {', '.join(arm_list)}")
    if "onlycode" in arm_list:
        click.echo(f"Persistent kernel: {persistent_kernel}")
    click.echo(f"Runs per arm: {num_runs}")
    click.echo(f"Parallel: {parallel}")
    click.echo(f"Fail-fast: {fail_fast}")
    click.echo(f"Use cache: {use_cache}")
    click.echo(f"Resume: {resume}")
    click.echo(f"Output dir: {results_dir}")
    click.echo(f"Claude binary: {claude_binary}")
    claude_version = get_claude_version(claude_binary)
    click.echo(f"Claude version: {claude_version}")
    click.echo()

    # --- Cache backend selection (only relevant when --use-cache) ---------------
    overlay_backend: Backend = "none"
    overlay_tmp_root = "/tmp"
    if use_cache:
        overlay_backend = detect_overlay_backend()
        if overlay_backend == "none":
            click.echo(
                "WARNING: --use-cache requested but no overlay backend available "
                "(no CAP_SYS_ADMIN and no fuse-overlayfs). Falling back to the "
                "default clone+venv path.",
                err=True,
            )
            use_cache = False
        else:
            click.echo(f"Overlay backend: {overlay_backend}")
            click.echo()
            _cleanup_stale_overlays(problems, overlay_tmp_root, overlay_backend)

    # Track overlay handles so Phase 3 can tear them down even on exception.
    overlay_handles: dict[str, _OverlayHandle] = {}

    # --- Phase 1: parallel clone + venv setup -----------------------------------
    click.echo("Phase 1: Setting up repos and venvs...")
    setup_map: dict[str, tuple[str, str]] = {}

    def _setup_one(problem: Problem) -> tuple[str, str, _OverlayHandle | None]:
        """Prefer cached setup when --use-cache is on; else fall back to plain clone."""
        if use_cache:
            # run_tag is a fixed string here, which means two concurrent
            # `swebench run --use-cache` invocations on overlapping filters
            # would collide on /tmp/swe-{id}-eval/. Deferred per PR scope;
            # assign a PID- or uuid-based tag here if that becomes a real
            # use case.
            try:
                merged, venv_dir, handle = _setup_problem_cached(
                    problem,
                    run_tag="eval",
                    overlay_tmp_root=overlay_tmp_root,
                    overlay_backend=overlay_backend,
                )
            except OverlayError as exc:
                click.echo(
                    f"  {problem.instance_id}: overlay mount failed ({exc}); "
                    "falling back to clone+venv.",
                    err=True,
                )
                repo_dir, venv_dir = _setup_problem(problem, clone_base)
                return (repo_dir, venv_dir, None)
            if handle is not None:
                return (merged, venv_dir, handle)
            click.echo(
                f"  {problem.instance_id}: not cached; falling back to clone+venv "
                f"(run 'python -m swebench cache setup --filter {problem.instance_id}' "
                "for fast startup)"
            )
        repo_dir, venv_dir = _setup_problem(problem, clone_base)
        return (repo_dir, venv_dir, None)

    if parallel == 1:
        # Serial setup — no thread overhead
        for problem in problems:
            click.echo(f"  Setting up {problem.instance_id}...")
            repo_dir, venv_dir, handle = _setup_one(problem)
            setup_map[problem.instance_id] = (repo_dir, venv_dir)
            if handle is not None:
                overlay_handles[problem.instance_id] = handle
    else:
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            future_to_id: dict[Future[tuple[str, str, _OverlayHandle | None]], str] = {}
            for problem in problems:
                fut = pool.submit(_setup_one, problem)
                future_to_id[fut] = problem.instance_id
            for fut in as_completed(future_to_id):
                pid = future_to_id[fut]
                try:
                    repo_dir, venv_dir, handle = fut.result()
                    setup_map[pid] = (repo_dir, venv_dir)
                    if handle is not None:
                        overlay_handles[pid] = handle
                    click.echo(f"  {pid}: setup complete")
                except Exception as exc:
                    click.echo(f"  {pid}: setup FAILED ({exc})", err=True)
                    # Tear down any overlays mounted so far before exiting.
                    for h in overlay_handles.values():
                        _teardown_overlay(h)
                    raise SystemExit(1)

    click.echo()

    # --- Phase 2: run arms -------------------------------------------------------
    click.echo("Phase 2: Running evaluation arms...")
    click.echo()

    def _teardown_all_overlays() -> None:
        for h in overlay_handles.values():
            _teardown_overlay(h)
        overlay_handles.clear()

    # Build arm tasks grouped by problem.  Each problem's arms must run
    # serially because they share one repo_dir (git working tree).
    #
    # When --resume is on, any (instance, arm, run) triple whose result files
    # already indicate a PASS/FAIL verdict is skipped at task-build time. This
    # keeps the skip decision in one place, so serial and parallel execution
    # paths see the exact same filtered task list.
    problem_tasks: dict[str, list[_ArmTask]] = {}
    for problem in problems:
        repo_dir, venv_dir = setup_map[problem.instance_id]
        # Cached instances run inside an overlay merged dir; git_reset's
        # `git clean -fd` wipes .egg-info there, so each arm must re-run
        # `pip install --no-deps -e` before the test suite runs.
        needs_reinstall = problem.instance_id in overlay_handles
        tasks: list[_ArmTask] = []
        for run_idx in range(1, num_runs + 1):
            run_arms = list(arm_list)
            if shuffle_arms and len(run_arms) > 1:
                random.shuffle(run_arms)
            for arm in run_arms:
                if resume:
                    verdict = _is_triple_complete(
                        str(results_dir), problem.instance_id, arm, run_idx
                    )
                    if verdict is not None:
                        click.echo(
                            f"  [{problem.instance_id} {arm} run {run_idx}] "
                            f"Skipping — already complete ({verdict})"
                        )
                        continue
                tasks.append(_ArmTask(
                    problem=problem,
                    arm=arm,
                    run_idx=run_idx,
                    repo_dir=repo_dir,
                    venv_dir=venv_dir,
                    needs_editable_reinstall=needs_reinstall,
                ))
        problem_tasks[problem.instance_id] = tasks

    if parallel == 1:
        # Serial execution — matches original behaviour exactly
        last_instance: str | None = None
        for pid, tasks in problem_tasks.items():
            for i, task in enumerate(tasks):
                if task.problem.instance_id != last_instance:
                    click.echo(f"--- Instance: {task.problem.instance_id} ---")
                    click.echo(f"  Repo: {task.problem.repo_slug}")
                    click.echo(f"  Base commit: {task.problem.base_commit}")
                    click.echo(f"  Test cmd: {task.problem.test_cmd}")
                    last_instance = task.problem.instance_id
                try:
                    verdict = _run_arm(
                        problem=task.problem,
                        arm=task.arm,
                        run_idx=task.run_idx,
                        repo_dir=task.repo_dir,
                        venv_dir=task.venv_dir,
                        results_dir=str(results_dir),
                        claude_binary=claude_binary,
                        mcp_config_path=mcp_config_path,
                        root=root,
                        persistent_kernel=persistent_kernel,
                        needs_editable_reinstall=task.needs_editable_reinstall,
                    )
                except BaseException:
                    _teardown_all_overlays()
                    raise
                click.echo()
                if fail_fast and verdict == "FAIL":
                    _teardown_all_overlays()
                    click.echo("FAIL detected with --fail-fast; stopping early.")
                    raise SystemExit(1)
                # Refresh the overlay between arms so the next arm sees a clean
                # lowerdir — avoids fuse-overlayfs EEXIST on copy-up'd files.
                # Note: we do NOT write the returned handle back to overlay_handles
                # because _refresh_overlay reuses the same merged/upper/work paths
                # (it wipes and remounts in place). Writing back would create a
                # concurrent write/iterate hazard in parallel mode since
                # _teardown_all_overlays iterates overlay_handles.values(). The
                # paths in overlay_handles remain valid throughout (Option B fix).
                if i < len(tasks) - 1:
                    handle = overlay_handles.get(pid)
                    if handle is not None and handle.lowerdir:
                        try:
                            _refresh_overlay(handle, task.venv_dir)
                        except BaseException:
                            _teardown_all_overlays()
                            raise
    else:
        # Parallel execution — one thread per problem.  Arms within each
        # problem run serially to avoid repo_dir race conditions.
        _fail_event = threading.Event()

        def _run_problem_tasks(tasks: list[_ArmTask]) -> list[tuple[str, str]]:
            """Run all arm tasks for one problem serially; returns list of (id, verdict)."""
            results: list[tuple[str, str]] = []
            pid = tasks[0].problem.instance_id if tasks else ""
            for i, task in enumerate(tasks):
                if _fail_event.is_set():
                    results.append((task.problem.instance_id, "CANCELLED"))
                    continue

                buf = io.StringIO()
                try:
                    verdict = _run_arm(
                        problem=task.problem,
                        arm=task.arm,
                        run_idx=task.run_idx,
                        repo_dir=task.repo_dir,
                        venv_dir=task.venv_dir,
                        results_dir=str(results_dir),
                        claude_binary=claude_binary,
                        mcp_config_path=mcp_config_path,
                        root=root,
                        persistent_kernel=persistent_kernel,
                        log_buffer=buf,
                        needs_editable_reinstall=task.needs_editable_reinstall,
                    )
                except Exception as exc:
                    stderr_detail = getattr(exc, "stderr", None)
                    buf.write(f"\nERROR: {exc}\n")
                    if stderr_detail:
                        buf.write(f"stderr: {stderr_detail}\n")
                    buf.write(traceback.format_exc())
                    verdict = "ERROR"

                header = (
                    f"--- Instance: {task.problem.instance_id} "
                    f"[{task.arm} run {task.run_idx}] ---"
                )
                _flush_buffer(header, buf)

                if fail_fast and verdict == "FAIL":
                    _fail_event.set()

                results.append((task.problem.instance_id, verdict))

                # Refresh the overlay between arms so the next arm sees a clean
                # lowerdir — avoids fuse-overlayfs EEXIST on copy-up'd files.
                # Note: we do NOT write the returned handle back to overlay_handles
                # because _refresh_overlay reuses the same merged/upper/work paths
                # (it wipes and remounts in place). Writing back would create a
                # concurrent write/iterate hazard since _teardown_all_overlays
                # (called from the main thread on exception) iterates
                # overlay_handles.values(). The paths in overlay_handles remain
                # valid throughout (Option B fix).
                if i < len(tasks) - 1:
                    handle = overlay_handles.get(pid)
                    if handle is not None and handle.lowerdir:
                        try:
                            _refresh_overlay(handle, task.venv_dir)
                        except BaseException:
                            _teardown_all_overlays()
                            raise
            return results

        try:
            with ThreadPoolExecutor(max_workers=parallel) as pool:
                futures = {
                    pool.submit(_run_problem_tasks, tasks): pid
                    for pid, tasks in problem_tasks.items()
                    if tasks  # every task was skipped by --resume; nothing to run
                }

                had_failure = False
                for fut in as_completed(futures):
                    try:
                        for instance_id, verdict in fut.result():
                            if verdict == "FAIL" and fail_fast:
                                had_failure = True
                    except Exception as exc:
                        click.echo(f"Thread raised an exception: {exc}", err=True)
                        if fail_fast:
                            had_failure = True

                    # Cancel remaining unstarted futures on failure
                    if had_failure and fail_fast:
                        for other_fut in futures:
                            other_fut.cancel()

            # Exit non-zero if any arm FAILed under --fail-fast. SystemExit is
            # a BaseException, so the outer except clause below will still run
            # _teardown_all_overlays() before the process exits.
            if had_failure:
                click.echo("FAIL detected — stopping.")
                raise SystemExit(1)
        except BaseException:
            _teardown_all_overlays()
            raise

    _teardown_all_overlays()
    click.echo(f"=== Done. Results in {results_dir}/ ===")
