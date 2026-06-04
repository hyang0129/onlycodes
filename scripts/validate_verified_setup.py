#!/usr/bin/env python3
"""Validate cache-build + test-collect for a SWE-bench problem set, emit the
buildable subset.

This is the C3 step of WS-A.2 (#308). It generalizes
``scripts/validate_datasci_mini_setup.py``: instead of the non-cached
``_setup_problem`` smoke-import path, it drives the **cache path the spine
actually runs** (``--use-cache``) and adds a test-collection gate, so a
``buildable`` verdict means "the spine's baseline arm will get past setup and
collect tests for this instance".

Two gates per instance, each in its own subprocess (so a segfault/timeout on
one instance never aborts the pass):

  Gate 1 — clone + venv-build:  reuse ``cache_cli._setup_one`` (clone bare →
      working tree → checkout → venv + editable install → scrub → lockfile →
      isolated ``venv_lower`` layout). This is exactly ``python -m swebench
      cache setup`` for one id, so the warmed cache is reusable by the spine.

  Gate 2 — run-test cleanly:  clone a throwaway tree from the now-cached bare
      repo, ``git reset`` to base, apply the held-out test patch, then
      ``run_preflight_collect`` (``pytest --collect-only``) against the built
      venv. ``buildable`` ⇔ collection yields >0 items. At base commit the
      FAIL_TO_PASS tests are *expected* to fail, so we deliberately do NOT run
      the suite — we only assert the environment can collect/import the tests.

      NOTE (fidelity): ``run_preflight_collect`` only applies to ``python -m
      pytest`` / ``python -m unittest`` commands. Repos whose test_cmd is a
      bespoke runner — notably Django's ``python tests/runtests.py …`` — get a
      no-op collect (returns True), so for those instances ``buildable`` ==
      "build succeeded + test patch applied". This matches the harness's own
      pre-flight behavior; it is not a bug introduced here. Such instances are
      flagged ``collect_skipped`` in the per-instance table.

Outputs land in ``runs/validation/<set-leaf>_<timestamp>/`` and are rewritten
after every instance, so an early kill on a multi-hour run still leaves partial
findings on disk:

    summary.md         per-instance table, failures grouped by class + fix hints
    results.json       machine-readable per-instance records
    buildable.txt      newline-delimited ids that built AND collected cleanly
    logs/<id>.log      full stdout+stderr for each instance subprocess

``--buildable-out PATH`` additionally writes the buildable list to a committed
location (e.g. ``sets/verified-buildable.txt`` for the full hand-off run).

The shortfall ``|pool| − |buildable|`` is reported loudly and never silently
truncated — "how many of the pool build" is the whole point of this issue.

Usage::

    # sample / iteration
    python scripts/validate_verified_setup.py --set swe/swebench-verified \
        --filter @/tmp/sample.txt --concurrency 4

    # full hand-off run (hours–days; tee to a log, monitor disk)
    python scripts/validate_verified_setup.py --set swe/swebench-verified \
        --concurrency 8 --buildable-out sets/verified-buildable.txt \
        2>&1 | tee /tmp/verified_build.log
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import textwrap
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "runs" / "validation"


def _conda_default() -> bool:
    """Default for ``--conda`` when the flag is unset — mirrors
    ``cache_cli.setup``'s ``ONLYCODES_CONDA_BUILD`` convention so the validator
    builds the same way the spine's ``cache setup`` does."""
    return os.environ.get("ONLYCODES_CONDA_BUILD", "").lower() in ("1", "true", "yes", "on")

# Throwaway clones for the Gate-2 collect check. The bare repo is local after
# Gate 1, so these clones are cheap; each is wiped before and after use.
DEFAULT_CLONE_BASE = "/tmp/swebench-verified-validate"


# (regex, failure_class, fix_hint). First match wins. Future agents can extend.
# Build-time patterns are shared with validate_datasci_mini_setup.py; the last
# two are collect-time patterns specific to this validator's Gate 2.
FAILURE_PATTERNS: list[tuple[str, str, str]] = [
    (
        r"No such file or directory: 'python3\.[0-9]+'|"
        r"FileNotFoundError.*python3\.[0-9]+|"
        r"No interpreter found for Python 3\.[0-9]+",
        "interpreter_unavailable",
        "The official spec calls for a Python the box doesn't have and uv can't "
        "fetch (3.5/3.6/3.7). Provision it via deadsnakes/pyenv (#311 follow-up, "
        "devcontainer change) — uv covers 3.8+ automatically.",
    ),
    (
        r"from collections import (Sequence|Mapping|MutableMapping|MutableSequence|Iterable|Iterator|Callable|Set)",
        "collections_abc_removed_3_10",
        "Pin this instance to python3.9 in _INSTANCE_PYTHON in swebench/harness.py "
        "(same pattern as astropy-6938 / scikit-learn-10427).",
    ),
    (
        r"types\.CodeType.*'bytes' object cannot be interpreted as an integer|"
        r"_make_cell_set_template_code",
        "vendored_cloudpickle_pre_3_8",
        "Vendored cloudpickle uses pre-3.8 types.CodeType signature. "
        "harness._patch_vendored_cloudpickle should have fixed this — "
        "check that the file path or pre-3.8 block hasn't drifted (#208).",
    ),
    (
        r"ModuleNotFoundError: No module named 'distutils'",
        "distutils_removed_3_12",
        "distutils was removed in Python 3.12. Pin python_bin to python3.11 "
        "or earlier via _INSTANCE_PYTHON / _REPO_PYTHON.",
    ),
    (
        r"setuptools\.dep_util|setuptools/dep_util",
        "setuptools_dep_util_removed",
        "setuptools.dep_util was removed in setuptools 71. Add 'setuptools<69' "
        "to this instance's pre_install (see astropy entries for reference).",
    ),
    (
        r"numpy\.distutils",
        "numpy_distutils_removed",
        "numpy.distutils was removed in numpy 1.26. Pin 'numpy<1.26' via pre_install.",
    ),
    (
        r"AttributeError: module 'numpy' has no attribute '(bool|int|float|object|str|long|complex)'",
        "numpy_alias_removed",
        "These numpy aliases were removed in numpy 1.20–1.24. Pin 'numpy<1.20' "
        "(or 'numpy<1.24' for the late deprecations) in pre_install.",
    ),
    (
        r"Microsoft Visual C\+\+|error: command 'gcc' failed|"
        r"error: command 'cc' failed|fatal error:.*\.h: No such file",
        "native_build_failure",
        "Native compile failed during pip install. Check for missing system "
        "headers (qhull, freetype, openblas, etc.) or a Cython/setuptools mismatch.",
    ),
    (
        r"Could not find a version that satisfies the requirement",
        "pip_resolver_failure",
        "Pip could not resolve a dependency — pinned versions likely incompatible "
        "with the chosen Python. Inspect the full log and adjust pre_install.",
    ),
    (
        r"jinja2\.environmentfilter|cannot import name 'environmentfilter'",
        "jinja2_environmentfilter_removed",
        "jinja2.environmentfilter removed in Jinja2 3.0. _needs_jinja2_pin in "
        "harness.py should have caught this — confirm the file shape it greps for.",
    ),
    (
        r"ImportError while importing test module|conftest\.py.*Error|"
        r"errors during collection",
        "test_collection_import_error",
        "A test module failed to import during collection (Gate 2). Usually a "
        "missing dep the held-out test needs or a repo-version API mismatch. "
        "Inspect the '--- pytest --collect-only ---' block in the log.",
    ),
    (
        r"No closing quotation|shlex\.split",
        "malformed_test_cmd",
        "test_cmd has an unparseable token — usually a FAIL_TO_PASS entry that "
        "is a prose test description (e.g. 'Named URLs should be reversible') "
        "rather than a dotted node id, so add.py:_build_test_cmd produced a "
        "malformed command. The instance built fine but cannot be collected/run "
        "as-is. Fix the YAML's test_cmd (drop the non-node-id tokens) or exclude "
        "the instance from the buildable pool.",
    ),
    (
        r"ModuleNotFoundError: No module named '([^']+)'",
        "module_not_found",
        "A module is missing from the built venv. Confirm the editable install "
        "succeeded and add the dependency to this instance's pre_install / "
        "post_install in swebench/harness.py if it is a test-only requirement.",
    ),
    (
        r"subprocess-exited-with-error|error: subprocess-exited-with-error",
        "build_backend_failure",
        "Build backend exited non-zero. Re-run the log to see the underlying "
        "traceback (usually a Cython/setuptools/numpy ABI issue).",
    ),
]


def classify(output: str) -> tuple[str, str] | None:
    for pat, label, hint in FAILURE_PATTERNS:
        if re.search(pat, output):
            return (label, hint)
    return None


# ---------------------------------------------------------------------------
# Per-instance worker — runs in a fresh subprocess. Gate 1 builds the cache
# (the same path `cache setup` uses); Gate 2 collects tests against the built
# venv via a throwaway clone. Emits a single JSON sentinel line on stdout.
# ---------------------------------------------------------------------------

WORKER_SCRIPT = r"""
import json, os, sys, shutil, traceback
sys.path.insert(0, {repo_root!r})
from pathlib import Path
from swebench import specs
from swebench.models import Problem
from swebench.cache import cache_paths, bare_repo_path
from swebench.cache_cli import _setup_one
from swebench.harness import (
    clone_from_bare, git_reset, apply_test_patch,
    run_preflight_collect, resolve_test_node_ids,
)
from swebench.run import _INSTANCE_ENV, _INSTANCE_EXTRA_PYTEST_ARGS

yaml_path = Path({yaml_path!r})
clone_base = {clone_base!r}
force = {force!r}
conda = {conda!r}
repo_root = {repo_root!r}

problem = Problem.from_yaml(yaml_path)
iid = problem.instance_id
result = {{"ok": False, "status": "build_fail", "reason": None,
          "lockfile": False, "collect_skipped": False, "conda": conda}}

try:
    # --- Gate 1: clone + venv-build (identical to `cache setup` for one id) ---
    # Under --conda, spec-bearing instances build conda-native (the faithful
    # MAP_REPO_VERSION_TO_SPECS path); instances without a spec fall back to venv.
    _id, built_ok, build_msg = _setup_one(problem, force=force, conda=conda)
    result["build_msg"] = build_msg
    paths = cache_paths(iid)
    if not built_ok:
        result["status"] = "build_fail"
        result["reason"] = build_msg
        print("__VALIDATOR_RESULT__" + json.dumps(result))
        sys.exit(0)
    result["lockfile"] = os.path.exists(paths["lockfile"])

    # --- Gate 2: run-test cleanly (pytest --collect-only > 0 items) ----------
    venv_dir = paths["venv_lower"] if os.path.exists(paths["venv_lower"]) else paths["venv"]
    tmp_repo = os.path.join(clone_base, iid)
    shutil.rmtree(tmp_repo, ignore_errors=True)
    try:
        clone_from_bare(str(bare_repo_path(problem.repo_slug)), tmp_repo)
        git_reset(tmp_repo, problem.base_commit)
        if problem.patch_file:
            patch_path = str(Path(repo_root) / problem.patch_file)
            if not apply_test_patch(tmp_repo, patch_path):
                result["status"] = "patch_fail"
                result["reason"] = "held-out test patch failed to apply at base commit"
                print("__VALIDATOR_RESULT__" + json.dumps(result))
                sys.exit(0)
        resolved = resolve_test_node_ids(
            problem.test_cmd, repo_dir=tmp_repo, venv_dir=venv_dir,
            repo_slug=problem.repo_slug,
        )
        # Collect-time env. Under --conda we run the collect faithfully under the
        # spec's `export`-style eval_commands (LANG/LC_ALL/... locale pins) — the
        # test-fidelity half of the conda-native build — with the hand-curated
        # _INSTANCE_ENV taking precedence (hand-tables > official-spec, per #311).
        # System-level eval_commands (locale-gen) need root and are skipped+logged,
        # exactly as setup_conda_env skips system-level pre_install.
        extra_env = dict(_INSTANCE_ENV.get(iid) or {{}})
        if conda:
            spec = specs.spec_for(problem.repo_slug, getattr(problem, "version", None))
            if spec:
                spec_env = specs.eval_env(spec)
                if spec_env:
                    extra_env = {{**spec_env, **extra_env}}
                    result["eval_env"] = spec_env
                skipped = specs.eval_system_commands(spec)
                if skipped:
                    result["eval_system_skipped"] = skipped
                    sys.stdout.write("\n--- spec eval_commands skipped (system-level, need root) ---\n")
                    for c in skipped:
                        sys.stdout.write(c + "\n")
        # run_preflight_collect returns (True, "") for non-pytest/-unittest
        # runners (e.g. Django runtests.py) — record that as collect_skipped so
        # the report is honest about which gate actually fired.
        is_pytest_like = (" -m pytest" in resolved) or (" -m unittest" in resolved)
        collected_ok, output = run_preflight_collect(
            repo_dir=tmp_repo, test_cmd=resolved, venv_dir=venv_dir,
            extra_env=extra_env or None,
            extra_pytest_args=_INSTANCE_EXTRA_PYTEST_ARGS.get(iid),
        )
        sys.stdout.write("\n--- pytest --collect-only (tail) ---\n")
        sys.stdout.write((output or "")[-4000:])
        sys.stdout.write("\n--- end collect-only ---\n")
        if collected_ok:
            result["ok"] = True
            result["status"] = "ok"
            result["reason"] = None
            result["collect_skipped"] = not is_pytest_like
        else:
            result["status"] = "collect_fail"
            result["reason"] = "pytest --collect-only returned 0 items (post test-patch)"
    except BaseException as exc:
        result["status"] = "collect_error"
        result["reason"] = "{{}}: {{}}".format(type(exc).__name__, exc)
        traceback.print_exc()
    finally:
        shutil.rmtree(tmp_repo, ignore_errors=True)
except BaseException as exc:
    result["status"] = result.get("status") or "error"
    result["reason"] = "{{}}: {{}}".format(type(exc).__name__, exc)
    traceback.print_exc()

print("__VALIDATOR_RESULT__" + json.dumps(result))
"""


def run_one(yaml_path: Path, *, clone_base: str, timeout: int, force: bool,
            conda: bool, log_dir: Path) -> dict:
    """Validate one instance in a subprocess. Always returns; never raises."""
    instance_id = yaml_path.stem
    log_file = log_dir / f"{instance_id}.log"

    code = WORKER_SCRIPT.format(
        repo_root=str(REPO_ROOT),
        yaml_path=str(yaml_path),
        clone_base=clone_base,
        force=force,
        conda=conda,
    )

    started = dt.datetime.now(dt.timezone.utc).isoformat()
    rc: int
    output: str
    timed_out = False
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=REPO_ROOT,
        )
        rc = proc.returncode
        output = (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        rc = -1
        output = (exc.stdout or b"").decode("utf-8", errors="replace") if exc.stdout else ""
        output += (exc.stderr or b"").decode("utf-8", errors="replace") if exc.stderr else ""
        output += f"\n[validator] subprocess timed out after {timeout}s\n"
        timed_out = True
    except Exception as exc:  # noqa: BLE001
        rc = -2
        output = f"[validator] subprocess launch failed: {exc!r}\n"
    finished = dt.datetime.now(dt.timezone.utc).isoformat()

    log_file.write_text(output)

    worker_result: dict | None = None
    for line in output.splitlines():
        if line.startswith("__VALIDATOR_RESULT__"):
            try:
                worker_result = json.loads(line[len("__VALIDATOR_RESULT__"):])
            except json.JSONDecodeError:
                worker_result = None
            break

    if timed_out:
        status = "timeout"
    elif worker_result is not None:
        status = worker_result.get("status", "fail")
        if worker_result.get("ok"):
            status = "ok"
    else:
        # Subprocess produced no sentinel — treat as a hard failure.
        status = "error"

    klass: str | None = None
    hint: str | None = None
    if status != "ok":
        cls = classify(output)
        if cls:
            klass, hint = cls

    return {
        "instance_id": instance_id,
        "status": status,
        "returncode": rc,
        "timed_out": timed_out,
        "reason": (worker_result or {}).get("reason"),
        "build_msg": (worker_result or {}).get("build_msg"),
        "lockfile": (worker_result or {}).get("lockfile", False),
        "collect_skipped": (worker_result or {}).get("collect_skipped", False),
        "conda": (worker_result or {}).get("conda", conda),
        "eval_env": (worker_result or {}).get("eval_env"),
        "eval_system_skipped": (worker_result or {}).get("eval_system_skipped"),
        "failure_class": klass,
        "fix_hint": hint,
        "log_file": str(log_file.relative_to(REPO_ROOT)),
        "started_utc": started,
        "finished_utc": finished,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def write_buildable(results: list[dict], paths: list[Path]) -> None:
    buildable = sorted(r["instance_id"] for r in results if r["status"] == "ok")
    body = "\n".join(buildable) + ("\n" if buildable else "")
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)


def write_summary(results: list[dict], out_path: Path, *, set_name: str,
                  start: dt.datetime, pool_size: int, conda: bool = False) -> None:
    total = len(results)
    ok = sum(1 for r in results if r["status"] == "ok")
    shortfall = pool_size - ok

    by_class: dict[str, list[dict]] = {}
    for r in results:
        if r["status"] != "ok":
            key = r["failure_class"] or r["status"] or "unclassified"
            by_class.setdefault(key, []).append(r)

    lines: list[str] = []
    lines.append(f"# Verified setup validation — `{set_name}`")
    lines.append("")
    lines.append(f"- Started (UTC): `{start.isoformat()}`")
    lines.append(f"- Pool size (validated): **{pool_size}**")
    lines.append(
        "- Build path: **"
        + ("conda-native (spec-faithful `MAP_REPO_VERSION_TO_SPECS`) + venv fallback "
           "for spec-less instances" if conda else "venv (generic)")
        + "**"
    )
    lines.append(f"- Buildable (built + collected cleanly): **{ok}**")
    lines.append(f"- **Shortfall (pool − buildable): {shortfall}**")
    lines.append("")
    lines.append("## What `buildable` means here")
    lines.append("")
    lines.append(textwrap.dedent("""
        Each instance passes two gates, each in its own subprocess:

        1. **clone + venv-build** — the exact path `python -m swebench cache
           setup` runs (bare clone → working tree → checkout → venv + editable
           install → scrub → lockfile → isolated venv_lower layout). The warmed
           cache is reusable by the spine.
        2. **run-test cleanly** — a throwaway clone at base commit + the
           held-out test patch + `pytest --collect-only`. `buildable` ⇔ >0 items
           collect. At base commit the FAIL_TO_PASS tests are *expected* to
           fail, so the suite is deliberately NOT run — only collection/import.

        `collect_skipped` marks instances whose test_cmd is a non-pytest runner
        (e.g. Django `runtests.py`), where `--collect-only` is a no-op and
        `buildable` == "build + test-patch applied". This mirrors the harness's
        own pre-flight; it is not weaker validation introduced here.

        Only `buildable.txt` ids feed #299's spine and #301's powered subset.
    """).strip())
    lines.append("")

    if conda:
        lines.append(textwrap.dedent("""
            Under conda-native build, Gate 1 builds each spec-bearing instance from
            `MAP_REPO_VERSION_TO_SPECS` verbatim (correct interpreter via micromamba,
            file-ref deps, custom install flags), and Gate 2 runs the collect under
            the spec's `export`-style `eval_commands` (locale pins). System-level
            `eval_commands` (`locale-gen`) need root and are skipped + logged in the
            per-instance log, the same way `setup_conda_env` skips system-level
            `pre_install`. Instances with no official spec fall back to the venv path.
        """).strip())
        lines.append("")

    lines.append("## Per-instance result")
    lines.append("")
    lines.append("| Instance | Status | Collect | Failure class | Reason / hint |")
    lines.append("|---|---|---|---|---|")
    icons = {
        "ok": "✅ ok", "build_fail": "❌ build", "patch_fail": "❌ patch",
        "collect_fail": "❌ collect", "collect_error": "❌ collect-err",
        "timeout": "⏱ timeout", "error": "❌ error", "fail": "❌ fail",
    }
    for r in results:
        icon = icons.get(r["status"], r["status"])
        collect = "skip" if r.get("collect_skipped") else ("—" if r["status"] != "ok" else "✓")
        klass = r["failure_class"] or ("" if r["status"] == "ok" else "unclassified")
        note = (r["fix_hint"] or r["reason"] or "").replace("|", "\\|")
        lines.append(f"| `{r['instance_id']}` | {icon} | {collect} | {klass} | {note} |")
    lines.append("")

    if by_class:
        lines.append("## Failures grouped by class")
        lines.append("")
        for klass in sorted(by_class.keys()):
            rows = by_class[klass]
            lines.append(f"### `{klass}` — {len(rows)} instance(s)")
            lines.append("")
            hint = rows[0]["fix_hint"] or "(no automated fix hint — inspect the log)"
            lines.append(f"**Suggested fix:** {hint}")
            lines.append("")
            for r in rows:
                reason = (r["reason"] or "").strip()
                suffix = f" — {reason}" if reason else ""
                lines.append(
                    f"- `{r['instance_id']}` (log: [`{r['log_file']}`]({r['log_file']})){suffix}"
                )
            lines.append("")

    lines.append("## Next steps")
    lines.append("")
    lines.append(textwrap.dedent("""
        1. For each failure class, apply the suggested fix in
           [`swebench/harness.py`](swebench/harness.py) (`_INSTANCE_PYTHON` /
           `_INSTANCE_PRE_INSTALL` / `_INSTANCE_ENV` tables), then re-run this
           validator with `--filter <id1>,<id2>,…` for just those instances.
        2. The shortfall above caps everything downstream — #308 reports it; it
           does not commit to fixing every non-builder.
        3. When satisfied, the committed `buildable.txt` is what #299's spine and
           #301's subset draw from (`run --filter @sets/verified-buildable.txt`).
    """).strip())
    lines.append("")
    out_path.write_text("\n".join(lines))


def _resolve_filter(filter_spec: str | None) -> set[str] | None:
    """Resolve --filter into a set of ids. Supports a comma list or @file
    (same convention as run.py's _parse_filter_ids)."""
    if not filter_spec:
        return None
    spec = filter_spec.strip()
    if spec.startswith("@"):
        path = Path(spec[1:]).expanduser()
        if not path.is_file():
            print(f"ERROR: --filter file not found: {path}", file=sys.stderr)
            sys.exit(1)
        ids: set[str] = set()
        for raw in path.read_text().splitlines():
            line = raw.split("#", 1)[0].strip()
            if line:
                ids.add(line)
        return ids
    return {s.strip() for s in spec.split(",") if s.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--set", dest="set_name", default="swe/swebench-verified",
        help="Problem set under problems/ to validate (default: swe/swebench-verified).",
    )
    parser.add_argument(
        "--filter", default=None,
        help="Comma-separated ids or @path/to/ids.txt (default: every YAML in the set).",
    )
    parser.add_argument(
        "--concurrency", type=int, default=4,
        help="Max instances to validate in parallel (default: 4). Cache builds are heavy.",
    )
    parser.add_argument(
        "--timeout", type=int, default=2400,
        help="Per-instance timeout in seconds (default: 2400 = 40 min).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Force a cache rebuild even if an entry already exists (Gate 1).",
    )
    parser.add_argument(
        "--clone-base", default=DEFAULT_CLONE_BASE,
        help=f"Throwaway clone base for the Gate-2 collect check (default: {DEFAULT_CLONE_BASE}).",
    )
    parser.add_argument(
        "--buildable-out", type=Path, default=None,
        help="Also write the buildable id list here (e.g. sets/verified-buildable.txt). "
             "Always written to the run dir's buildable.txt regardless.",
    )
    parser.add_argument(
        "--conda", action=argparse.BooleanOptionalAction, default=None,
        help="Build spec-bearing instances conda-native (faithful "
             "MAP_REPO_VERSION_TO_SPECS via micromamba) in Gate 1, and run the Gate-2 "
             "collect under the spec's eval_commands env (locale pins). Instances "
             "without an official spec fall back to the venv path. Defaults to the "
             "ONLYCODES_CONDA_BUILD env var (falsey if unset). Requires micromamba in "
             "the image (#311).",
    )
    args = parser.parse_args()

    if args.concurrency < 1:
        print("ERROR: --concurrency must be >= 1.", file=sys.stderr)
        return 2

    conda = _conda_default() if args.conda is None else args.conda
    if conda:
        # Fail loudly up front rather than letting every instance fall back or
        # error mid-run: conda-native builds need micromamba, which is baked into
        # the devcontainer image (#311). A pre-rebuild container won't have it.
        # REPO_ROOT on the path so the import works when run as a bare script
        # (the worker subprocess does the same before its own swebench imports).
        sys.path.insert(0, str(REPO_ROOT))
        from swebench.harness import _find_micromamba
        if _find_micromamba() is None:
            print(
                "ERROR: --conda requested but micromamba was not found. The "
                "conda-native build needs micromamba (baked at /usr/local/bin by the "
                "devcontainer image — rebuild the container, or set ONLYCODES_MICROMAMBA "
                "to its path). Re-run with --no-conda for the generic venv path. (#311)",
                file=sys.stderr,
            )
            return 2

    problems_dir = REPO_ROOT / "problems" / args.set_name
    if not problems_dir.is_dir():
        print(f"ERROR: problem set not found: {problems_dir}", file=sys.stderr)
        return 2

    all_yaml = sorted(problems_dir.glob("*.yaml"))
    wanted = _resolve_filter(args.filter)
    if wanted is not None:
        yamls = [p for p in all_yaml if p.stem in wanted]
        missing = wanted - {p.stem for p in yamls}
        if missing:
            print(f"warning: unknown instance IDs ignored: {sorted(missing)}", file=sys.stderr)
    else:
        yamls = all_yaml

    if not yamls:
        print(f"ERROR: no YAMLs to validate in {problems_dir} (filter={args.filter}).",
              file=sys.stderr)
        return 2

    Path(args.clone_base).mkdir(parents=True, exist_ok=True)

    start = dt.datetime.now(dt.timezone.utc)
    stamp = start.strftime("%Y%m%dT%H%M%SZ")
    set_leaf = args.set_name.rstrip("/").split("/")[-1]
    out_dir = RUNS_DIR / f"{set_leaf}_{stamp}"
    log_dir = out_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    pool_size = len(yamls)

    print(f"=== {set_leaf} setup validation ===")
    print(f"Instances:   {pool_size}")
    print(f"Concurrency: {args.concurrency}")
    print(f"Timeout:     {args.timeout}s per instance")
    print(f"Build path:  {'conda-native (spec-faithful) + venv fallback' if conda else 'venv (generic)'}")
    print(f"Output dir:  {out_dir.relative_to(REPO_ROOT)}")
    print(f"Started:     {start.isoformat()}")
    print(flush=True)

    results: list[dict] = []
    lock = threading.Lock()
    buildable_targets = [out_dir / "buildable.txt"]
    if args.buildable_out:
        buildable_targets.append(args.buildable_out)

    def _flush() -> None:
        # Stable order by instance id for deterministic diffs.
        ordered = sorted(results, key=lambda r: r["instance_id"])
        (out_dir / "results.json").write_text(json.dumps(ordered, indent=2))
        write_summary(ordered, out_dir / "summary.md", set_name=args.set_name,
                      start=start, pool_size=pool_size, conda=conda)
        write_buildable(ordered, buildable_targets)

    done = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futs = {
            pool.submit(run_one, yp, clone_base=args.clone_base,
                        timeout=args.timeout, force=args.force, conda=conda,
                        log_dir=log_dir): yp
            for yp in yamls
        }
        for fut in as_completed(futs):
            r = fut.result()
            with lock:
                results.append(r)
                done += 1
                tag = r["failure_class"] or r["status"]
                extra = " (collect skipped)" if r.get("collect_skipped") else ""
                marker = "ok" if r["status"] == "ok" else r["status"].upper()
                print(f"[{done:>3}/{pool_size}] {r['instance_id']}: {marker} ({tag}){extra}",
                      flush=True)
                _flush()

    ok = sum(1 for r in results if r["status"] == "ok")
    shortfall = pool_size - ok
    print()
    print(f"Done. Buildable: {ok}/{pool_size}.  SHORTFALL: {shortfall}")
    print(f"Summary:   {(out_dir / 'summary.md').relative_to(REPO_ROOT)}")
    print(f"Buildable: {(out_dir / 'buildable.txt').relative_to(REPO_ROOT)}")
    if args.buildable_out:
        print(f"           (also written to {args.buildable_out})")

    # Exit 0 regardless — the report is the deliverable, and a non-zero exit
    # would conflict with the "keep going on every failure" goal of this run.
    return 0


if __name__ == "__main__":
    sys.exit(main())
