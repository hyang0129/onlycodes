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

from swebench.runner import ClaudeRunner as _ClaudeRunner

# ---------------------------------------------------------------------------
# Per-repo Python interpreter and pre-install pin tables
# ---------------------------------------------------------------------------

_DEFAULT_PYTHON = "python3.11"

_REPO_PYTHON: dict[str, str] = {
    # scikit-learn 0.20–0.22: setuptools ≥ 61 + Cython 0.29 ABI mismatch on 3.11
    "scikit-learn/scikit-learn": "python3.10",
}

_REPO_PRE_INSTALL: dict[str, list[str]] = {
    # scikit-learn 0.20–0.22: pins required before `pip install -e .`
    "scikit-learn/scikit-learn": ["setuptools<60", "numpy<1.24", "cython<3"],
    # matplotlib 3.1 era: numpy 2.x ABI break + old setuptools/cython.
    # certifi is required: matplotlib's build downloads freetype/qhull tarballs
    # over HTTPS and imports certifi for the CA bundle.  Without it, build
    # fails with "ImportError: `certifi` is unavailable" before any C compile.
    "matplotlib/matplotlib": ["setuptools<65", "numpy<2", "cython<3", "pybind11>=2.6", "certifi"],
}

# ---------------------------------------------------------------------------
# Per-instance overrides (take precedence over repo-level entries above)
# ---------------------------------------------------------------------------
# Use instance_id as the key (format: <category>__<slug>).
# An absent key → fall through to the repo-level table.
# An explicit [] (empty list) → suppress the repo-level pin for this instance.

_INSTANCE_PYTHON: dict[str, str] = {
    # astropy 3.x era (2018): uses collections.MutableSequence removed in 3.10+
    "astropy__astropy-6938": "python3.9",
    # scikit-learn 0.19–0.20 era (2018): uses collections.Sequence removed in 3.10+
    "scikit-learn__scikit-learn-10427": "python3.9",
    "scikit-learn__scikit-learn-10803": "python3.9",
    "scikit-learn__scikit-learn-11206": "python3.9",
    # scikit-learn 0.18 era (2017): uses collections.abc removed in 3.10+
    "scikit-learn__scikit-learn-3840": "python3.9",
    # sympy 1.0–1.1 era (2016–2017): uses collections.abc removed in 3.10+
    "sympy__sympy-11232": "python3.9",
    "sympy__sympy-13259": "python3.9",
    "sympy__sympy-14180": "python3.9",
}

_INSTANCE_PRE_INSTALL: dict[str, list[str]] = {
    # astropy 3.x era (2018): setuptools.dep_util removed in setuptools 71
    "astropy__astropy-6938":  ["setuptools<69", "numpy<2", "cython<3", "extension-helpers"],
    # astropy 5.x era (2022): same issue
    "astropy__astropy-12962": ["setuptools<69", "numpy<2", "cython<3", "extension-helpers"],
    "astropy__astropy-13842": ["setuptools<69", "numpy<2", "cython<3", "extension-helpers"],
    # matplotlib 3.7 era (2023): uses pybind11 + downloads qhull (needs certifi);
    # repo-level setuptools<65 is too old for this version's pyproject.toml build.
    "matplotlib__matplotlib-26160": ["numpy<2", "cython<3", "pybind11>=2.6", "certifi", "wheel"],
    # scikit-learn 1.2–1.3 era: setup.py's check_package_status() imports scipy
    # at metadata-generation time, before any editable install. Without scipy
    # pre-installed, build fails with "scikit-learn requires scipy >= 1.3.2".
    # scipy<1.12 keeps compatibility with the repo-level numpy<1.24 pin.
    "scikit-learn__scikit-learn-24677": ["setuptools<60", "numpy<1.24", "cython<3", "scipy<1.12"],
    "scikit-learn__scikit-learn-25694": ["setuptools<60", "numpy<1.24", "cython<3", "scipy<1.12"],
}

# ---------------------------------------------------------------------------
# Slug → top-level importable module name (for smoke-import checks)
# ---------------------------------------------------------------------------
# Only repos in datasci-mini are listed — unknown repos are silently skipped.

_TOPLEVEL_MODULE: dict[str, str] = {
    "scikit-learn/scikit-learn": "sklearn",
    "matplotlib/matplotlib":     "matplotlib",
    "astropy/astropy":           "astropy",
    "pandas-dev/pandas":         "pandas",
    "numpy/numpy":               "numpy",
    "sympy/sympy":               "sympy",
}


def _venv_kwargs(problem: "Problem") -> dict:  # type: ignore[name-defined]
    """Per-instance + per-repo overrides for ``setup_venv()``, ``**``-unpackable.

    Lookup precedence (highest → lowest):
      1. ``_INSTANCE_PRE_INSTALL`` / ``_INSTANCE_PYTHON`` keyed by ``instance_id``
      2. ``_REPO_PRE_INSTALL`` / ``_REPO_PYTHON`` keyed by ``repo_slug``
      3. Built-in defaults (``_DEFAULT_PYTHON``, no pre-install pins)

    An explicit ``[]`` in an instance table suppresses the repo-level pin for
    that instance (distinct from an absent key which falls through).

    Also passes ``repo_slug`` through so ``setup_venv`` can call ``_smoke_import``.
    """
    pre = _INSTANCE_PRE_INSTALL.get(problem.instance_id)
    if pre is None:
        pre = _REPO_PRE_INSTALL.get(problem.repo_slug)
    python_bin = _INSTANCE_PYTHON.get(
        problem.instance_id,
        _REPO_PYTHON.get(problem.repo_slug, _DEFAULT_PYTHON),
    )
    return {
        "python_bin": python_bin,
        "pre_install": pre,
        "repo_slug": problem.repo_slug,
    }

# Sentinel file written inside the venv dir to record which python binary
# created it.  A mismatch triggers a full venv rebuild.
_SENTINEL_FILENAME = ".python_bin"


def _venv_sentinel(venv_dir: str) -> str:
    """Return the path to the python_bin sentinel file inside *venv_dir*."""
    return os.path.join(venv_dir, _SENTINEL_FILENAME)


def _read_sentinel(venv_dir: str) -> str | None:
    """Read and return the sentinel value, or None if absent/unreadable."""
    try:
        return Path(_venv_sentinel(venv_dir)).read_text().strip()
    except OSError:
        return None

# Per-slug locks so concurrent cache-setup threads don't race on the same bare clone.
_bare_clone_locks: dict[str, threading.Lock] = {}
_bare_clone_locks_mu = threading.Lock()


def get_claude_version(claude_binary: str) -> str:
    """Shim — delegates to ClaudeRunner.get_version()."""
    return _ClaudeRunner().get_version(claude_binary)


def find_claude_binary() -> str:
    """Shim — delegates to ClaudeRunner.find_binary()."""
    return _ClaudeRunner().find_binary()


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


def _needs_jinja2_pin(repo_dir: str) -> bool:
    """Return True if the repo uses jinja2.environmentfilter, removed in Jinja2 3.0.

    Old Sphinx versions (< 4.0) import `environmentfilter` from jinja2, which was
    removed in Jinja2 3.0. Detected by grepping the installed source so the check
    is version-agnostic and doesn't require hard-coding instance IDs.
    """
    candidate = os.path.join(repo_dir, "sphinx", "util", "rst.py")
    if not os.path.isfile(candidate):
        return False
    try:
        with open(candidate) as f:
            return "environmentfilter" in f.read()
    except OSError:
        return False


def _pin_jinja2(pip: str) -> None:
    """Pin Jinja2 to >=2.11,<3.0 — the last series compatible with Python 3.11
    that still exports environmentfilter."""
    result = subprocess.run(
        [pip, "install", "--quiet", "jinja2<3.0,>=2.11"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            f"[harness] jinja2 pin failed (rc={result.returncode}):\n{result.stderr}",
            flush=True,
        )
        raise subprocess.CalledProcessError(
            result.returncode, result.args, result.stdout, result.stderr
        )


def _smoke_import(venv_dir: str, repo_slug: str) -> None:
    """Confirm the installed package actually imports cleanly.

    ``pip install -e .`` can return exit 0 even when C extensions silently bind
    to the wrong numpy ABI (e.g. matplotlib 3.1 built against numpy 1.x, then
    numpy 2 installed later).  The failure surfaces only at import time.

    Only runs when ``repo_slug`` is in ``_TOPLEVEL_MODULE``; unknown repos are
    silently skipped to avoid spurious failures.

    Raises ``RuntimeError`` on a non-zero import exit so the sentinel is never
    written and the next ``setup_venv`` call rebuilds from scratch.
    """
    module = _TOPLEVEL_MODULE.get(repo_slug)
    if not module:
        return  # unknown repo — skip rather than fail spuriously
    python = os.path.join(venv_dir, "bin", "python")
    result = subprocess.run(
        [python, "-c", f"import {module}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"venv smoke-import of `{module}` failed:\n{result.stderr}"
        )


def _pip_run_checked(pip: str, args: list[str]) -> None:
    """Run pip with the given args; on failure, print captured stderr then raise."""
    result = subprocess.run([pip, *args], capture_output=True, text=True)
    if result.returncode != 0:
        print(
            f"[harness] pip {args[0]} failed (rc={result.returncode}):\n{result.stderr}",
            flush=True,
        )
        raise subprocess.CalledProcessError(
            result.returncode, [pip, *args], result.stdout, result.stderr
        )


def setup_venv(
    venv_dir: str,
    repo_dir: str,
    *,
    python_bin: str = _DEFAULT_PYTHON,
    pre_install: list[str] | None = None,
    repo_slug: str | None = None,
) -> None:
    """Create a venv and pip install the project in editable mode (if not already done).

    Parameters
    ----------
    venv_dir:
        Directory where the virtual environment lives (created if absent).
    repo_dir:
        Root of the project to install in editable mode.
    python_bin:
        Python interpreter to use when creating a *fresh* venv (e.g.
        ``"python3.10"``).  Defaults to ``_DEFAULT_PYTHON`` (``"python3.11"``).
        Ignored when reusing an existing venv whose sentinel matches.
    pre_install:
        Optional list of pip requirement specs to install *before* the
        editable install (e.g. ``["setuptools<60", "numpy<1.24", "cython<3"]``).
        When non-empty, the editable install uses ``--no-build-isolation`` so
        the pinned packages are visible during the build.  Only applied on the
        fresh-venv creation path.
    repo_slug:
        Optional repo slug (e.g. ``"matplotlib/matplotlib"``).  When provided,
        a smoke-import check is run on the fresh-venv path to catch ABI
        mismatches that ``pip install`` silently ignores.  The check is skipped
        for slugs not in ``_TOPLEVEL_MODULE`` and skipped entirely on the venv
        reuse path (a reused venv has already imported cleanly at least once).
    """
    pip = os.path.join(venv_dir, "bin", "pip")
    if os.path.isdir(venv_dir):
        # F-19: Guard against a partially-built venv skeleton that has the
        # directory but not bin/pip (e.g. venv creation crashed mid-way).
        if not os.path.isfile(pip):
            shutil.rmtree(venv_dir, ignore_errors=True)
        elif _read_sentinel(venv_dir) != python_bin:
            # Sentinel mismatch: the venv was created with a different Python
            # binary.  Wipe and fall through to the fresh-create path.
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
            if _needs_jinja2_pin(repo_dir):
                _pin_jinja2(pip)
            return
    # Fresh venv creation path.
    subprocess.run(
        [python_bin, "-m", "venv", venv_dir],
        check=True,
        capture_output=True,
    )
    # Pre-install setuptools/wheel so old projects using setup.py + pkg_resources
    # can build under pip's build isolation without hitting ModuleNotFoundError.
    _pip_run_checked(pip, ["install", "--quiet", "setuptools", "wheel"])
    if pre_install:
        # Install pinned build dependencies before the editable install so the
        # build backend sees the correct versions.  --no-build-isolation ensures
        # the already-installed pins are used during the build (not re-resolved
        # from scratch inside an isolated build env).
        _pip_run_checked(pip, ["install", "--quiet", *pre_install])
        _pip_run_checked(pip, ["install", "--quiet", "-e", repo_dir, "--no-build-isolation"])
    else:
        _pip_run_checked(pip, ["install", "--quiet", "-e", repo_dir])
    # Try common test/dev extras; ignore failures (not all packages define them).
    for extra in ("test", "tests", "dev", "testing"):
        subprocess.run(
            [pip, "install", "--quiet", "-e", f"{repo_dir}[{extra}]"],
            capture_output=True,
            text=True,
        )
    # Always ensure pytest is present as a final fallback.
    _pip_run_checked(pip, ["install", "--quiet", "pytest"])
    if _needs_jinja2_pin(repo_dir):
        _pin_jinja2(pip)
    # Smoke-import: confirm the package actually imports before writing the
    # sentinel.  A failed smoke-import leaves the venv unmarked so the next
    # setup_venv call rebuilds from scratch rather than silently reusing a
    # broken venv.  Only runs on known repos (_TOPLEVEL_MODULE); unknown
    # repos are silently skipped to avoid spurious failures.
    if repo_slug:
        _smoke_import(venv_dir, repo_slug)
    # Write the sentinel last — only after a fully successful install.
    Path(_venv_sentinel(venv_dir)).write_text(python_bin + "\n")


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
    """Shim — creates an isolated Claude config dir with only credentials.

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
    """Shim — delegates to ClaudeRunner.invoke(). Non-zero exit does not raise."""
    _ClaudeRunner().invoke(
        prompt=prompt,
        cwd=repo_dir,
        system_prompt=system_prompt,
        tools_flags=tools_flags,
        result_file=result_file,
        binary=claude_binary,
    )


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
