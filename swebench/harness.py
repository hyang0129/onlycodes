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
    # pyparsing<3 is required: matplotlib 3.3–3.7 registers
    # `error::PyparsingDeprecationWarning` as a pytest warning filter, and
    # pyparsing 3.x emits that warning on legacy camelCase APIs (setParseAction,
    # parseString, enablePackrat, ...) used throughout matplotlib's
    # fontconfig_pattern/mathtext modules, causing test collection to ERROR
    # before any test runs.
    "matplotlib/matplotlib": ["setuptools<65", "numpy<2", "cython<3", "pybind11>=2.6", "certifi", "pyparsing<3"],
    # seaborn ≤0.12 era: seaborn/cm.py calls matplotlib.cm.register_cmap at import,
    # removed in matplotlib 3.9 (deprecated 3.7). Without this pin, conftest crashes
    # and 0 tests collect → automatic FAIL.
    "mwaskom/seaborn": ["matplotlib<3.7", "numpy<2"],
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
    # scikit-learn 0.19–0.22.dev era (2018–2019): Cython .pyx files incompatible with Cython 3.x on Python 3.10+
    "scikit-learn__scikit-learn-10427": "python3.9",
    "scikit-learn__scikit-learn-13013": "python3.9",
    "scikit-learn__scikit-learn-10803": "python3.9",
    "scikit-learn__scikit-learn-11206": "python3.9",
    "scikit-learn__scikit-learn-13283": "python3.9",
    "scikit-learn__scikit-learn-13496": "python3.9",
    "scikit-learn__scikit-learn-13864": "python3.9",
    "scikit-learn__scikit-learn-14125": "python3.9",
    "scikit-learn__scikit-learn-14710": "python3.9",
    "scikit-learn__scikit-learn-15094": "python3.9",
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
    # astropy 5.x era (2022): same issue. setuptools_scm is required at test-import
    # time because astropy/version.py calls scm_version.get_version() during
    # `import astropy`. Without it, every test errors with "No module named 'setuptools_scm'".
    "astropy__astropy-12962": ["setuptools<69", "numpy<2", "cython<3", "extension-helpers", "setuptools_scm"],
    "astropy__astropy-13842": ["setuptools<69", "numpy<2", "cython<3", "extension-helpers", "setuptools_scm"],
    # matplotlib 3.7 era (2023): uses pybind11 + downloads qhull (needs certifi);
    # repo-level setuptools<65 is too old for this version's pyproject.toml build.
    # pyparsing<3 mirrors the repo-level pin (instance override fully replaces it).
    "matplotlib__matplotlib-26160": ["numpy<2", "cython<3", "pybind11>=2.6", "certifi", "wheel", "pyparsing<3"],
    # xarray 0.12–2022.x (pre-numpy-2): xarray/core/dtypes.py references np.unicode_
    # which was removed in NumPy 2.0. Without a numpy<2 pin, every test errors with
    # "AttributeError: `np.unicode_` was removed in the NumPy 2.0 release".
    # pytz is required at test-module import time (xarray/tests/test_variable.py).
    "pydata__xarray-2905": ["numpy<2", "pytz"],
    "pydata__xarray-4075": ["numpy<2"],
    "pydata__xarray-4629": ["numpy<2"],
    "pydata__xarray-4911": ["numpy<2"],
    "pydata__xarray-6601": ["numpy<2", "setuptools_scm[toml]>=3.4", "setuptools_scm_git_archive"],
    "pydata__xarray-7003": ["numpy<2", "setuptools_scm[toml]>=3.4", "setuptools_scm_git_archive"],
    # scikit-learn 0.20-era: tests import sklearn.externals._pilutil (a vendored
    # copy of scipy.misc.pilutil) which requires Pillow at import time. Without
    # Pillow pre-installed, collection fails with ModuleNotFoundError.
    "scikit-learn__scikit-learn-10427": ["setuptools<60", "numpy<1.24", "cython<3", "Pillow"],
    # scikit-learn 0.20–0.21.dev era: pinned scipy needed at runtime because
    # scipy.optimize.linesearch.line_search_wolfe2 was removed in scipy 1.8.
    # scipy<1.6 matches the adjacent 0.21.dev entries below.
    "scikit-learn__scikit-learn-13013": ["setuptools<60", "numpy<1.24", "cython<3", "scipy<1.6"],
    # scikit-learn 0.21.dev–0.22.dev era (2019): _cython_blas.pyx imports scipy.linalg.cython_blas
    # at pre-build time. Without scipy pre-installed, Cython can't resolve the BLAS function
    # pointers and the build fails with "Converting to Python object not allowed without gil".
    # scipy<1.6 is the last release supporting Python 3.9 with old numpy.
    "scikit-learn__scikit-learn-13283": ["setuptools<60", "numpy<1.24", "cython<3", "scipy<1.6"],
    "scikit-learn__scikit-learn-13496": ["setuptools<60", "numpy<1.24", "cython<3", "scipy<1.6"],
    "scikit-learn__scikit-learn-13864": ["setuptools<60", "numpy<1.24", "cython<3", "scipy<1.6"],
    "scikit-learn__scikit-learn-14125": ["setuptools<60", "numpy<1.24", "cython<3", "scipy<1.6"],
    "scikit-learn__scikit-learn-14710": ["setuptools<60", "numpy<1.24", "cython<3", "scipy<1.6"],
    "scikit-learn__scikit-learn-15094": ["setuptools<60", "numpy<1.24", "cython<3", "scipy<1.6"],
    # scikit-learn 1.2–1.3 era: setup.py's check_package_status() imports scipy
    # at metadata-generation time, before any editable install. Without scipy
    # pre-installed, build fails with "scikit-learn requires scipy >= 1.3.2".
    # scipy<1.12 keeps compatibility with the repo-level numpy<1.24 pin.
    "scikit-learn__scikit-learn-24677": ["setuptools<60", "numpy<1.24", "cython<3", "scipy<1.12"],
    "scikit-learn__scikit-learn-25694": ["setuptools<60", "numpy<1.24", "cython<3", "scipy<1.12"],
    # sphinx 2.x era: sphinx/writers/latex.py imports the `roman` package
    # unconditionally; without it conftest crashes before any test collects.
    "sphinx-doc__sphinx-8056": ["roman"],
    # sphinx 4.3 era: applehelp and devhelp both enforce Sphinx ≥5.0 in their
    # version checks during fixture setup; markupsafe 2.1+ removed soft_unicode
    # breaking jinja2 2.x import. All three pins required for collection.
    "sphinx-doc__sphinx-9698": ["sphinxcontrib.applehelp<1.0.5", "sphinxcontrib-devhelp<1.0.6", "markupsafe<2.1"],
    # seaborn 0.12 era (2022): numpy 2.x removed np.str_ etc. used in cm.py;
    # flit_core is required at build time for this instance's pyproject.toml.
    "mwaskom__seaborn-2946": ["matplotlib<3.7", "numpy<2", "flit_core>=3.2,<4"],
}

# ---------------------------------------------------------------------------
# Per-instance source seed patches
# ---------------------------------------------------------------------------
# Paths are relative to the problems root (same convention as patch_file in
# YAML). Applied to the repo BEFORE the test patch so that test-patch imports
# of agent-created modules succeed at pre-flight collection time.
_INSTANCE_SOURCE_SEEDS: dict[str, str] = {
    # sklearn 0.20-era: the test patch imports sklearn.externals._pilutil which
    # the agent is expected to create as its fix. Without a stub the pre-flight
    # --collect-only fails before the agent ever runs.
    "scikit-learn__scikit-learn-10427": "patches/scikit-learn__scikit-learn-10427_source_seed.patch",
}

# ---------------------------------------------------------------------------
# Per-instance post-install pins
# ---------------------------------------------------------------------------
# Applied AFTER ``pip install -e .`` to re-pin packages that the editable
# install would otherwise upgrade (e.g. Sphinx pulls its sphinxcontrib-*
# extensions as runtime deps, overriding pre-install pins).
_INSTANCE_POST_INSTALL: dict[str, list[str]] = {
    # sphinx 4.3 era: pip install -e . resolves Sphinx's runtime deps and
    # upgrades devhelp / qthelp / htmlhelp / serializinghtml to 2.x releases
    # that require Sphinx ≥5.0. Force them back down after the editable install.
    "sphinx-doc__sphinx-9698": [
        "sphinxcontrib-devhelp<1.0.6",
        "sphinxcontrib-qthelp<1.0.4",
        "sphinxcontrib-htmlhelp<2.0.0",
        "sphinxcontrib-serializinghtml<1.1.5",
    ],
}

# ---------------------------------------------------------------------------
# Per-repo parallel pre-build commands
# ---------------------------------------------------------------------------
# Repos with large Cython extension sets take 20+ minutes to compile serially
# via ``pip install -e .``.  Running ``build_ext --inplace -j N`` first lets
# setuptools reuse the already-compiled ``.so`` files during the subsequent
# editable install, cutting total setup time by ~8x on 8-core machines.
# Only runs on the fresh-venv path; the reuse path skips it.

_N_BUILD_JOBS: int = min(4, max(1, os.cpu_count() or 1))

_REPO_PRE_BUILD: dict[str, list[str]] = {
    # sklearn 1.x uses setup.py build_ext which supports -j since Python 3.8.
    # Capped at 4: sklearn's generated C files are large (some ~1-2 GB RAM each
    # during compilation), so running more than 4 in parallel causes OOM kills.
    "scikit-learn/scikit-learn": [
        "python", "setup.py", "build_ext", "--inplace", f"-j{_N_BUILD_JOBS}",
    ],
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
    pre_build_cmd = _REPO_PRE_BUILD.get(problem.repo_slug)
    post = _INSTANCE_POST_INSTALL.get(problem.instance_id)
    return {
        "python_bin": python_bin,
        "pre_install": pre,
        "post_install": post,
        "pre_build_cmd": pre_build_cmd,
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


_VENDORED_CLOUDPICKLE_REL = (
    "sklearn/externals/joblib/externals/cloudpickle/cloudpickle.py"
)

_CLOUDPICKLE_OLD_BLOCK = (
    "        return types.CodeType(\n"
    "            co.co_argcount,\n"
    "            co.co_kwonlyargcount,\n"
)

_CLOUDPICKLE_NEW_BLOCK = (
    "        return types.CodeType(\n"
    "            co.co_argcount,\n"
    "            co.co_posonlyargcount,\n"
    "            co.co_kwonlyargcount,\n"
)


def _patch_vendored_cloudpickle(repo_dir: str) -> bool:
    """Make scikit-learn's vendored cloudpickle import-safe on Python 3.8+.

    The vendored copy in sklearn 0.20-era checkouts calls ``types.CodeType``
    with the pre-3.8 13-argument signature in ``_make_cell_set_template_code``.
    Python 3.8 added ``co_posonlyargcount`` as the 2nd parameter, so importing
    sklearn raises ``TypeError: 'bytes' object cannot be interpreted as an
    integer`` on every interpreter available in this devcontainer (3.9+).

    The fix inserts ``co.co_posonlyargcount`` into the PY3 branch — the same
    change cloudpickle upstream shipped in v1.3. Adjacent sklearn versions
    have multiple ``types.CodeType()`` callsites with the same pre-3.8 shape
    (e.g. ``_make_skel_func`` alongside ``_make_cell_set_template_code``), so
    we replace every matching block in the file, not just the first.
    Idempotent and a no-op when the file is missing or already patched.

    Returns True when the file was modified (useful for logging/tests).
    """
    path = Path(repo_dir) / _VENDORED_CLOUDPICKLE_REL
    if not path.is_file():
        return False
    text = path.read_text()
    if "co.co_posonlyargcount" in text:
        return False
    if _CLOUDPICKLE_OLD_BLOCK not in text:
        return False
    path.write_text(text.replace(_CLOUDPICKLE_OLD_BLOCK, _CLOUDPICKLE_NEW_BLOCK))
    return True


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
    post_install: list[str] | None = None,
    pre_build_cmd: list[str] | None = None,
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
    pre_build_cmd:
        Optional command (list of strings) to run after pre_install but before
        the editable install, executed with the venv's Python as the interpreter
        (``"python"`` in the list is substituted with the venv python path).
        Intended for repos with large Cython extension sets (e.g. scikit-learn)
        where running ``build_ext --inplace -j N`` in parallel first lets the
        subsequent ``pip install -e .`` skip recompilation.  Only runs on the
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
            # Patch vendored cloudpickle if needed (overlay refresh restored the
            # unpatched file from the cached lowerdir).
            _patch_vendored_cloudpickle(repo_dir)
            # F-1: capture stderr and surface failures rather than silently continuing.
            # --no-build-isolation matches the fresh-venv install (line 682): build deps
            # were pinned during initial pre_install and remain in the venv. Without it,
            # pip pulls latest setuptools into an isolated build env, breaking old repos
            # (e.g. astropy 5.x fails to build under setuptools >= 71).
            result = subprocess.run(
                [pip, "install", "--quiet", "--no-deps", "--no-build-isolation", "-e", repo_dir],
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
    # Patch vendored cloudpickle (sklearn 0.20-era) before any import of the
    # repo. No-op when the file is missing or already patched — see
    # _patch_vendored_cloudpickle for the rationale.
    _patch_vendored_cloudpickle(repo_dir)
    if pre_install:
        # Install pinned build dependencies before the editable install so the
        # build backend sees the correct versions.  --no-build-isolation ensures
        # the already-installed pins are used during the build (not re-resolved
        # from scratch inside an isolated build env).
        _pip_run_checked(pip, ["install", "--quiet", *pre_install])
        if pre_build_cmd:
            # Compile C/Cython extensions in parallel before the editable install.
            # When .so files are already present and newer than .pyx sources,
            # the subsequent pip install -e . skips recompilation (~seconds vs ~25 min).
            venv_python = os.path.join(venv_dir, "bin", "python")
            cmd = [venv_python if tok == "python" else tok for tok in pre_build_cmd]
            result = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True)
            if result.returncode != 0:
                print(
                    f"[harness] pre-build command failed (rc={result.returncode}):\n"
                    f"{result.stderr}",
                    flush=True,
                )
                raise subprocess.CalledProcessError(
                    result.returncode, cmd, result.stdout, result.stderr
                )
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
    if post_install:
        # Re-pin runtime deps after all other installs (including extras) so
        # nothing downstream can upgrade them back.
        _pip_run_checked(pip, ["install", "--quiet", *post_install])
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
    """Apply a test patch to the repo and commit it. Returns True if successful.

    Committing the patch (rather than leaving it as an unstaged diff) prevents
    agents from reading the test assertions via ``git diff`` — Issue #226.
    """
    if not os.path.isfile(patch_path):
        return False
    result = subprocess.run(
        ["git", "-C", repo_dir, "apply", patch_path],
        capture_output=True,
    )
    if result.returncode != 0:
        return False
    env = os.environ.copy()
    env.update({
        "GIT_AUTHOR_NAME": "swebench",
        "GIT_AUTHOR_EMAIL": "swebench@localhost",
        "GIT_AUTHOR_DATE": "1970-01-01T00:00:00+0000",
        "GIT_COMMITTER_NAME": "swebench",
        "GIT_COMMITTER_EMAIL": "swebench@localhost",
        "GIT_COMMITTER_DATE": "1970-01-01T00:00:00+0000",
    })
    subprocess.run(
        ["git", "-C", repo_dir, "add", "-A"],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", repo_dir, "commit", "-m", "test patch"],
        capture_output=True,
        env=env,
        check=True,
    )
    return True


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
