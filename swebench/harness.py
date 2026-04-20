"""Shared subprocess wrappers for git, claude binary, venv setup, and test running."""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

# Per-slug locks so concurrent cache-setup threads don't race on the same bare clone.
_bare_clone_locks: dict[str, threading.Lock] = {}
_bare_clone_locks_mu = threading.Lock()


def get_claude_version(claude_binary: str) -> str:
    """Return the version string reported by `claude --version`, or 'unknown'."""
    try:
        proc = subprocess.run(
            [claude_binary, "--version"],
            capture_output=True, text=True, timeout=10,
        )
        return proc.stdout.strip() or proc.stderr.strip() or "unknown"
    except Exception:
        return "unknown"


def find_claude_binary() -> str:
    """Locate the claude binary — PATH first, then VS Code extension glob.

    Returns the path to the claude binary, or raises FileNotFoundError.
    """
    # Check CLAUDE env var first
    claude_env = os.environ.get("CLAUDE")
    if claude_env and os.path.isfile(claude_env) and os.access(claude_env, os.X_OK):
        return claude_env

    # Check PATH
    claude_path = shutil.which("claude")
    if claude_path:
        return claude_path

    # Try VS Code extension path
    for ext_dir in sorted(
        glob.glob("/home/vscode/.vscode-server/extensions/anthropic.claude-code-*-linux-x64"),
        reverse=True,
    ):
        candidate = os.path.join(ext_dir, "resources", "native-binary", "claude")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    raise FileNotFoundError(
        "claude binary not found. Set CLAUDE= or install Claude Code."
    )


def git_reset(repo_dir: str, commit: str) -> None:
    """Hard-reset a repo to a given commit and clean untracked files.

    Compiled C extension binaries (*.so, *.pyd) are excluded from the clean so
    that packages like matplotlib — which compile extensions into the source tree
    during ``pip install -e .`` — remain importable after the reset.  Agents on
    SWE-bench fix Python source, not C code, so preserving these files across
    resets does not meaningfully affect evaluation isolation.
    """
    for cmd in [
        ["git", "-C", repo_dir, "reset", "--hard", commit, "--quiet"],
        # git clean -e uses gitignore pattern syntax: '*.so' matches at any depth
        ["git", "-C", repo_dir, "clean", "-fd", "--quiet",
         "-e", "*.so", "-e", "*.pyd"],
    ]:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode,
                cmd,
                output=result.stdout,
                stderr=result.stderr,
            )


def strip_git_history(repo_dir: str) -> None:
    """Reduce a repo to a single orphan root commit at the current worktree state.

    After this call, ``git log --all --oneline`` in ``repo_dir`` prints exactly
    one line (the orphan root), ``rev-list --all --count`` returns ``1``, and
    nothing in ``.git/objects/info/alternates``, ``.git/packed-refs``, or
    ``.git/logs/`` references pre-strip objects.

    This is how the SWE-bench harness prevents an agent under evaluation from
    recovering the upstream reference fix via ``git log``/``git show``/etc.

    The procedure is idempotent: re-running on an already-stripped repo is a
    no-op (still results in a single orphan commit with the same tree).

    Ordering (the alternates file and reflog must be handled carefully):

    1. Record the current branch name (HEAD may be symbolic or detached).
    2. Create an orphan commit at the current HEAD's tree via ``commit-tree``.
    3. Repoint the current branch (or HEAD if detached) at the new orphan SHA.
    4. Delete every other ref: other local branches, all remote-tracking refs,
       all tags, and the packed-refs file.
    5. Delete ``.git/logs/`` so ``git reflog`` cannot surface pre-strip SHAs.
    6. Run ``git repack -a -d`` so objects borrowed via alternates are pulled
       into a local pack — required before the alternates file is removed or
       the new orphan commit's tree/blobs become unreachable.
    7. Delete ``.git/objects/info/alternates``.
    8. Run ``git gc --prune=now`` to drop the now-unreachable pre-strip
       objects. With alternates gone and reflog gone, only the orphan commit
       and its tree/blobs remain reachable.

    Only the working tree at ``repo_dir`` is touched. Any bare repo that
    ``repo_dir`` was previously borrowing objects from (via ``--local
    --shared`` alternates) is left unchanged — the strip materialises those
    objects locally first, then severs the link.
    """
    def _run(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            ["git", "-C", repo_dir, *args],
            capture_output=True,
            text=True,
        )
        if check and proc.returncode != 0:
            raise subprocess.CalledProcessError(
                proc.returncode,
                ["git", "-C", repo_dir, *args],
                output=proc.stdout,
                stderr=proc.stderr,
            )
        return proc

    # 1. Detect current branch. If HEAD is detached, `symbolic-ref HEAD` exits
    # non-zero; in that case we rewrite HEAD directly.
    sym = _run(["symbolic-ref", "-q", "HEAD"], check=False)
    current_ref = sym.stdout.strip() if sym.returncode == 0 else ""  # e.g. "refs/heads/main"

    # 2. Create orphan commit with the same tree as the current HEAD.
    tree = _run(["rev-parse", "HEAD^{tree}"]).stdout.strip()
    # Use GIT_AUTHOR_*/GIT_COMMITTER_* to make the orphan SHA deterministic
    # for a given tree — helpful for idempotency testing but not load-bearing.
    env = os.environ.copy()
    env.update({
        "GIT_AUTHOR_NAME": "swebench",
        "GIT_AUTHOR_EMAIL": "swebench@localhost",
        "GIT_AUTHOR_DATE": "1970-01-01T00:00:00+0000",
        "GIT_COMMITTER_NAME": "swebench",
        "GIT_COMMITTER_EMAIL": "swebench@localhost",
        "GIT_COMMITTER_DATE": "1970-01-01T00:00:00+0000",
    })
    proc = subprocess.run(
        ["git", "-C", repo_dir, "commit-tree", tree, "-m", "base"],
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode,
            ["git", "-C", repo_dir, "commit-tree", tree, "-m", "base"],
            output=proc.stdout,
            stderr=proc.stderr,
        )
    new_sha = proc.stdout.strip()

    # 3. Repoint the current branch (or HEAD if detached) at the orphan commit.
    # We write the loose ref file directly rather than using `git update-ref`
    # because `update-ref` is a no-op when the target SHA already matches —
    # which happens on idempotent re-runs (same tree + fixed author/date =>
    # same orphan SHA). A no-op means the ref stays only in ``packed-refs``,
    # and step 4 below deletes that file, leaving the branch unreachable.
    # Writing the loose file unconditionally guarantees the ref survives
    # ``packed-refs`` removal.
    if current_ref:
        loose_path = os.path.join(repo_dir, ".git", *current_ref.split("/"))
        os.makedirs(os.path.dirname(loose_path), exist_ok=True)
        with open(loose_path, "w") as f:
            f.write(new_sha + "\n")
    else:
        # Detached HEAD: rewrite HEAD directly.
        _run(["update-ref", "--no-deref", "HEAD", new_sha])

    # 4. Delete every other ref: other local branches, remote refs, tags, packed-refs.
    # Enumerate every ref and delete those that aren't the current branch.
    refs_proc = _run(["for-each-ref", "--format=%(refname)"])
    for refname in refs_proc.stdout.splitlines():
        refname = refname.strip()
        if not refname:
            continue
        if refname == current_ref:
            continue
        # --no-deref so we delete the ref itself, not what it points to.
        _run(["update-ref", "-d", refname], check=False)
    packed_refs = os.path.join(repo_dir, ".git", "packed-refs")
    if os.path.isfile(packed_refs):
        os.remove(packed_refs)

    # 5. Delete the reflog so `git reflog` can't surface pre-strip SHAs.
    logs_dir = os.path.join(repo_dir, ".git", "logs")
    shutil.rmtree(logs_dir, ignore_errors=True)

    # 6. Pack all reachable objects locally — required before removing alternates.
    # -a: include all objects reachable from refs; -d: remove redundant packs/loose.
    _run(["repack", "-a", "-d"])

    # 7. Remove the alternates file so future reads cannot reach the shared bare repo.
    alternates = os.path.join(repo_dir, ".git", "objects", "info", "alternates")
    if os.path.isfile(alternates):
        os.remove(alternates)

    # 8. Drop now-unreachable objects (the original history). --prune=now forces
    # immediate pruning rather than the default 2-week grace period.
    _run(["gc", "--prune=now", "--quiet"])


def clone_repo(repo_slug: str, dest: str) -> None:
    """Clone a GitHub repo if not already cloned."""
    if os.path.isdir(os.path.join(dest, ".git")):
        return
    subprocess.run(
        ["gh", "repo", "clone", repo_slug, dest, "--", "--quiet"],
        check=True,
        capture_output=True,
    )


def clone_bare_repo(repo_slug: str, bare_dest: str) -> None:
    """Create a bare clone of a GitHub repo if one does not already exist.

    Bare clones are the shared source for ``clone_from_bare``; they let many
    per-instance working trees share one set of pack files on disk.

    Thread-safe: concurrent callers for the same slug serialize on a per-slug
    lock so only one clone runs; the rest return immediately once HEAD exists.
    """
    with _bare_clone_locks_mu:
        lock = _bare_clone_locks.setdefault(repo_slug, threading.Lock())

    with lock:
        if os.path.isdir(bare_dest) and os.path.isfile(
            os.path.join(bare_dest, "HEAD")
        ):
            return
        os.makedirs(os.path.dirname(bare_dest), exist_ok=True)
        subprocess.run(
            ["gh", "repo", "clone", repo_slug, bare_dest, "--", "--bare", "--quiet"],
            check=True,
            capture_output=True,
        )


def clone_from_bare(bare_src: str, dest: str) -> None:
    """Clone a working tree from a local bare repo (``--local --shared``).

    Much faster than a fresh network clone — shares ``.git/objects`` with the
    bare repo via hardlinks/alternates. Safe to call repeatedly; no-op if
    ``dest/.git`` already exists.

    .. warning::
        ``--shared`` writes ``dest/.git/objects/info/alternates`` pointing at
        ``bare_src``.  If the bare repo is deleted while this working tree still
        exists, every git operation on ``dest`` (reset, status, log, …) will
        fail with "object not found".  Always remove all instance caches that
        reference a bare repo **before** deleting the bare repo itself.  The
        ``cache clean --include-bare`` command enforces this invariant.
    """
    if os.path.isdir(os.path.join(dest, ".git")):
        return
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    subprocess.run(
        ["git", "clone", "--local", "--shared", "--quiet", bare_src, dest],
        check=True,
        capture_output=True,
    )


def setup_venv(venv_dir: str, repo_dir: str) -> None:
    """Create a venv and pip install the project in editable mode (if not already done)."""
    pip = os.path.join(venv_dir, "bin", "pip")
    if os.path.isdir(venv_dir):
        # F-19: Guard against a partially-built venv skeleton that has the
        # directory but not bin/pip (e.g. venv creation crashed mid-way).
        # If pip is missing, wipe the directory so the new-venv branch below
        # recreates it cleanly.
        if not os.path.isfile(pip):
            shutil.rmtree(venv_dir, ignore_errors=True)
        else:
            # Venv exists from a prior run. Re-run the editable install so that C
            # extension .so files are recompiled if git clean removed them (fast no-op
            # when they already exist). Also ensure pytest is present.
            # F-1: capture stderr and surface failures rather than silently continuing.
            result = subprocess.run(
                [pip, "install", "--quiet", "--no-deps", "-e", repo_dir],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print(
                    f"[harness] pip editable-install failed (rc={result.returncode}):\n"
                    f"{result.stderr}",
                    flush=True,
                )
                raise subprocess.CalledProcessError(
                    result.returncode, result.args, result.stdout, result.stderr
                )
            result = subprocess.run(
                [pip, "install", "--quiet", "pytest"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print(
                    f"[harness] pip install pytest failed (rc={result.returncode}):\n"
                    f"{result.stderr}",
                    flush=True,
                )
                raise subprocess.CalledProcessError(
                    result.returncode, result.args, result.stdout, result.stderr
                )
            return
    subprocess.run(
        ["python3.11", "-m", "venv", venv_dir],
        check=True,
        capture_output=True,
    )
    # Pre-install setuptools/wheel so old projects using setup.py + pkg_resources
    # can build under pip's build isolation without hitting ModuleNotFoundError.
    subprocess.run(
        [pip, "install", "--quiet", "setuptools", "wheel"],
        capture_output=True,
        text=True,
        check=True,
    )
    subprocess.run(
        [pip, "install", "--quiet", "-e", repo_dir],
        capture_output=True,
        text=True,
        check=True,
    )
    # Try common test/dev extras; ignore failures (not all packages define them).
    for extra in ("test", "tests", "dev", "testing"):
        subprocess.run(
            [pip, "install", "--quiet", "-e", f"{repo_dir}[{extra}]"],
            capture_output=True,
            text=True,
        )
    # Always ensure pytest is present as a final fallback.
    subprocess.run(
        [pip, "install", "--quiet", "pytest"],
        capture_output=True,
        text=True,
        check=True,
    )


def apply_test_patch(repo_dir: str, patch_path: str) -> bool:
    """Apply a test patch to the repo. Returns True if successful."""
    if not os.path.isfile(patch_path):
        return False
    result = subprocess.run(
        ["git", "-C", repo_dir, "apply", patch_path],
        capture_output=True,
    )
    return result.returncode == 0


def make_isolated_claude_config() -> str:
    """Create an isolated Claude config directory with only credentials.

    Returns the path to the temp directory. Caller must clean up.
    """
    cfg_dir = tempfile.mkdtemp(prefix="claude-eval-")
    for fname in (".credentials.json", ".claude.json"):
        src = os.path.expanduser(f"~/.claude/{fname}")
        if os.path.isfile(src):
            shutil.copy2(src, cfg_dir)
    return cfg_dir


def generate_mcp_config(base_config_path: str, cwd: str) -> str:
    """Generate a per-run MCP config with cwd set to the target repo.

    Returns the path to the temp config file. Caller must clean up.
    """
    if not os.path.isfile(base_config_path):
        return base_config_path

    with open(base_config_path) as f:
        config = json.load(f)

    # Set cwd on the codebox server only (matches run_swebench.sh behavior)
    codebox = config.get("mcpServers", {}).get("codebox")
    if codebox is not None:
        codebox["cwd"] = cwd

    tmp = tempfile.NamedTemporaryFile(
        prefix="mcp-config-",
        suffix=".json",
        mode="w",
        delete=False,
    )
    json.dump(config, tmp)
    tmp.close()
    return tmp.name


def run_claude(
    *,
    prompt: str,
    repo_dir: str,
    system_prompt: str,
    tools_flags: list[str],
    result_file: str,
    claude_binary: str,
) -> None:
    """Run the claude binary with isolated config. Non-zero exit does not raise."""
    cfg_dir = make_isolated_claude_config()
    try:
        cmd = [
            claude_binary,
            "-p", prompt,
            "--model", "claude-sonnet-4-6",
            "--system-prompt", system_prompt,
            *tools_flags,
            "--dangerously-skip-permissions",
            "--no-session-persistence",
            "--output-format", "stream-json",
            "--verbose",
        ]

        env = os.environ.copy()
        env["CLAUDE_CONFIG_DIR"] = cfg_dir

        with open(result_file, "w") as out:
            subprocess.run(cmd, cwd=repo_dir, stdout=out, stderr=subprocess.STDOUT, env=env)
    finally:
        shutil.rmtree(cfg_dir, ignore_errors=True)


def run_tests(
    *,
    repo_dir: str,
    test_cmd: str,
    venv_dir: str,
    result_file: str,
) -> str:
    """Run the test suite and write results. Returns 'PASS' or 'FAIL'."""
    # Replace leading 'python' with venv python
    venv_python = os.path.join(venv_dir, "bin", "python")
    if test_cmd.startswith("python "):
        effective_cmd = venv_python + test_cmd[len("python"):]
    else:
        effective_cmd = test_cmd

    with open(result_file, "w") as out:
        proc = subprocess.run(
            effective_cmd,
            shell=True,
            cwd=repo_dir,
            stdout=out,
            stderr=subprocess.STDOUT,
        )

    verdict = "PASS" if proc.returncode == 0 else "FAIL"

    with open(result_file, "a") as out:
        out.write(f"\n{verdict}\n")

    return verdict
