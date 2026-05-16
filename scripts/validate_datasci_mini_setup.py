#!/usr/bin/env python3
"""Validate venv setup + smoke-import for every datasci-mini instance.

For each YAML in ``problems/swe/swebench-datasci-mini/`` this driver runs the
exact ``_setup_problem`` path that ``python -m swebench run`` uses for
non-cached instances:

    clone_repo -> git_reset(base_commit) -> strip_git_history -> setup_venv

``setup_venv`` invokes ``_smoke_import`` on the fresh path, so a successful
return is a real signal that the venv can ``import <toplevel_module>`` without
error. Each instance runs in its own subprocess so any kind of failure
(exception, timeout, segfault) is captured and the next instance still runs —
the goal is to surface every import-time problem in a single pass.

Outputs land in ``runs/validation/datasci_mini_<timestamp>/``:

    summary.md         human + agent readable: per-instance table, failures
                       grouped by class, fix hints, next-steps section
    results.json       machine-readable per-instance result records
    logs/<id>.log      full stdout+stderr for each instance subprocess

``results.json`` and ``summary.md`` are rewritten after every instance, so an
early kill still leaves partial findings on disk.

Usage::

    python scripts/validate_datasci_mini_setup.py [--filter id1,id2,...]
                                                  [--timeout SECONDS]
                                                  [--clone-base PATH]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROBLEMS_DIR = REPO_ROOT / "problems" / "swe" / "swebench-datasci-mini"
RUNS_DIR = REPO_ROOT / "runs" / "validation"

# Default clone base — same location run.py uses for non-cached instances.
DEFAULT_CLONE_BASE = "/tmp/swebench-validate"


# (regex, failure_class, fix_hint). First match wins. Future agents can extend.
FAILURE_PATTERNS: list[tuple[str, str, str]] = [
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


def extract_smoke_traceback(output: str) -> str | None:
    """Return the smoke-import traceback substring if it appears."""
    m = re.search(
        r"venv smoke-import of `[^`]+` failed:\s*\n(.+?)(?:\n\n|\Z)",
        output,
        flags=re.DOTALL,
    )
    return m.group(1).strip() if m else None


# ---------------------------------------------------------------------------
# Per-instance worker — runs in a fresh subprocess, never imports unrelated
# repo state. Returns its result by writing to stdout as a single JSON line
# the parent then parses.
# ---------------------------------------------------------------------------

WORKER_SCRIPT = r"""
import json, os, sys, traceback, shutil
sys.path.insert(0, {repo_root!r})
from pathlib import Path
from swebench.models import Problem
from swebench.run import _setup_problem

yaml_path = Path({yaml_path!r})
clone_base = {clone_base!r}
problem = Problem.from_yaml(yaml_path)

# Always wipe any prior partial state for this instance so the validation is
# from-scratch every time. _setup_problem also rmtrees repo_dir, but it does
# not wipe the venv_dir — we do that explicitly to force the smoke-import.
repo_dir = os.path.join(clone_base, problem.instance_id)
venv_dir = os.path.join(clone_base, "venvs", problem.instance_id)
shutil.rmtree(repo_dir, ignore_errors=True)
shutil.rmtree(venv_dir, ignore_errors=True)

try:
    _setup_problem(problem, clone_base)
    print("__VALIDATOR_RESULT__" + json.dumps({{"ok": True}}))
except BaseException as exc:
    tb = traceback.format_exc()
    print("__VALIDATOR_RESULT__" + json.dumps({{
        "ok": False,
        "exc_type": type(exc).__name__,
        "exc_str": str(exc),
        "traceback": tb,
    }}))
"""


def run_one(yaml_path: Path, *, clone_base: str, timeout: int, log_dir: Path) -> dict:
    """Validate one instance in a subprocess. Always returns; never raises."""
    instance_id = yaml_path.stem
    log_file = log_dir / f"{instance_id}.log"

    code = WORKER_SCRIPT.format(
        repo_root=str(REPO_ROOT),
        yaml_path=str(yaml_path),
        clone_base=clone_base,
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
        output = f"[validator] subprocess launch failed: {exc!r}\n" + traceback.format_exc()
    finished = dt.datetime.now(dt.timezone.utc).isoformat()

    log_file.write_text(output)

    # Pull the structured result line if the worker reached it.
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
        status = "ok" if worker_result.get("ok") else "fail"
    elif rc == 0:
        # Subprocess succeeded but didn't emit our sentinel — treat as fail.
        status = "fail"
    else:
        status = "fail"

    klass: str | None = None
    hint: str | None = None
    smoke_tb: str | None = None
    if status != "ok":
        cls = classify(output)
        if cls:
            klass, hint = cls
        smoke_tb = extract_smoke_traceback(output)

    return {
        "instance_id": instance_id,
        "status": status,
        "returncode": rc,
        "timed_out": timed_out,
        "worker_exc_type": (worker_result or {}).get("exc_type"),
        "worker_exc_str": (worker_result or {}).get("exc_str"),
        "failure_class": klass,
        "fix_hint": hint,
        "smoke_import_traceback": smoke_tb,
        "log_file": str(log_file.relative_to(REPO_ROOT)),
        "started_utc": started,
        "finished_utc": finished,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def write_summary(results: list[dict], out_path: Path, start: dt.datetime, clone_base: str) -> None:
    total = len(results)
    ok = sum(1 for r in results if r["status"] == "ok")
    failed = total - ok

    by_class: dict[str, list[dict]] = {}
    for r in results:
        if r["status"] != "ok":
            key = r["failure_class"] or "unclassified"
            by_class.setdefault(key, []).append(r)

    lines: list[str] = []
    lines.append("# datasci-mini setup validation")
    lines.append("")
    lines.append(f"- Started (UTC): `{start.isoformat()}`")
    lines.append(f"- Clone base: `{clone_base}`")
    lines.append(f"- Total instances: **{total}**")
    lines.append(f"- Setup OK: **{ok}**")
    lines.append(f"- Setup FAILED: **{failed}**")
    lines.append("")
    lines.append("## What this report measures")
    lines.append("")
    lines.append(textwrap.dedent("""
        Each row corresponds to one validator subprocess that ran the
        non-cached setup path used by `python -m swebench run`:

            clone_repo -> git_reset(base_commit) -> strip_git_history -> setup_venv

        `setup_venv` invokes `_smoke_import(venv_dir, repo_slug)` on the
        fresh-venv path, so a row is `ok` iff `import <toplevel_module>`
        succeeded in that venv. Failures are classified by regex against
        the captured output (see `FAILURE_PATTERNS` in this script).

        This validator does NOT exercise OverlayFS / the instance cache,
        and does NOT run any tests or any Claude arms. Passing here is
        necessary but not sufficient for a full SWE-bench run — test-time
        failures (e.g. missing system libs) won't show up here.
    """).strip())
    lines.append("")

    lines.append("## Per-instance result")
    lines.append("")
    lines.append("| Instance | Status | Failure class | Fix hint |")
    lines.append("|---|---|---|---|")
    for r in results:
        icon = {"ok": "✅ ok", "fail": "❌ fail", "timeout": "⏱ timeout"}.get(
            r["status"], r["status"]
        )
        klass = r["failure_class"] or ("" if r["status"] == "ok" else "unclassified")
        hint = (r["fix_hint"] or "").replace("|", "\\|")
        lines.append(f"| `{r['instance_id']}` | {icon} | {klass} | {hint} |")
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
                lines.append(f"- `{r['instance_id']}` (log: [`{r['log_file']}`]({r['log_file']}))")
                if r["smoke_import_traceback"]:
                    tail = r["smoke_import_traceback"].splitlines()[-6:]
                    lines.append("  ```")
                    for tb_line in tail:
                        lines.append(f"  {tb_line}")
                    lines.append("  ```")
            lines.append("")

    lines.append("## Next steps for a future agent")
    lines.append("")
    lines.append(textwrap.dedent("""
        1. For each failure class above, apply the suggested fix in
           [`swebench/harness.py`](swebench/harness.py)
           (`_INSTANCE_PYTHON` and/or `_INSTANCE_PRE_INSTALL` tables).
        2. Re-run this validator with `--filter <id1>,<id2>,…` for just the
           instances you changed.
        3. Once every instance is `ok`, the D1–D5 batches in
           [`docs/BATCHED_RUN_SWE.md`](docs/BATCHED_RUN_SWE.md) will not hit
           Phase-1 surprises.
    """).strip())
    lines.append("")
    out_path.write_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--timeout", type=int, default=1800,
        help="Per-instance timeout in seconds (default: 1800 = 30 min).",
    )
    parser.add_argument(
        "--filter", type=str, default=None,
        help="Comma-separated instance IDs to validate (default: all 50).",
    )
    parser.add_argument(
        "--clone-base", type=str, default=DEFAULT_CLONE_BASE,
        help=f"Where to clone repos and create venvs (default: {DEFAULT_CLONE_BASE}). "
             "Will be created if absent. Each instance gets <base>/<id>/ and "
             "<base>/venvs/<id>/. Wiped per-instance before each validation.",
    )
    args = parser.parse_args()

    Path(args.clone_base).mkdir(parents=True, exist_ok=True)

    all_yaml = sorted(PROBLEMS_DIR.glob("*.yaml"))
    if args.filter:
        wanted = {x.strip() for x in args.filter.split(",") if x.strip()}
        yamls = [p for p in all_yaml if p.stem in wanted]
        missing = wanted - {p.stem for p in yamls}
        if missing:
            print(f"warning: unknown instance IDs ignored: {sorted(missing)}",
                  file=sys.stderr)
    else:
        yamls = all_yaml

    start = dt.datetime.now(dt.timezone.utc)
    stamp = start.strftime("%Y%m%dT%H%M%SZ")
    out_dir = RUNS_DIR / f"datasci_mini_{stamp}"
    log_dir = out_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    print("=== datasci-mini setup validation ===")
    print(f"Instances:  {len(yamls)}")
    print(f"Clone base: {args.clone_base}")
    print(f"Timeout:    {args.timeout}s per instance")
    print(f"Output dir: {out_dir.relative_to(REPO_ROOT)}")
    print(f"Started:    {start.isoformat()}")
    print()

    results: list[dict] = []
    for idx, yaml_path in enumerate(yamls, start=1):
        iid = yaml_path.stem
        print(f"[{idx:2d}/{len(yamls)}] {iid} ...", end=" ", flush=True)
        r = run_one(
            yaml_path,
            clone_base=args.clone_base,
            timeout=args.timeout,
            log_dir=log_dir,
        )
        results.append(r)
        if r["status"] == "ok":
            print("ok")
        else:
            tag = r["failure_class"] or "unclassified"
            print(f"{r['status'].upper()} ({tag})")

        (out_dir / "results.json").write_text(json.dumps(results, indent=2))
        write_summary(results, out_dir / "summary.md", start, args.clone_base)

    print()
    ok = sum(1 for r in results if r["status"] == "ok")
    print(f"Done. {ok}/{len(results)} instances passed setup.")
    print(f"Summary:  {out_dir.relative_to(REPO_ROOT)}/summary.md")
    print(f"Raw JSON: {out_dir.relative_to(REPO_ROOT)}/results.json")

    # Exit 0 regardless — the report is the deliverable, and a non-zero exit
    # would conflict with the "keep going on every failure" goal of this run.
    return 0


if __name__ == "__main__":
    sys.exit(main())
