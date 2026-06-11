"""Verbatim SWE-bench grading via the official ``run_evaluation`` (Concern B, #354).

This is the entire *grading / env* half of the verbatim-grading transition
(``docs/VERBATIM_GRADING_PLAN.md``): given a ``predictions.jsonl``
(``{instance_id, model_name_or_path, model_patch}``), grade **byte-for-byte**
through ``python -m swebench.harness.run_evaluation`` against the **unmodified**
official prebuilt image. We never touch an eval image; the agent harness
(Concern A) only produces the ``model_patch`` that crosses the seam.

Why a subprocess in an isolated venv:

* The upstream ``swebench`` PyPI package collides with our own ``swebench/``
  package name, so it cannot be imported in-process (same constraint as
  :mod:`swebench.official_grade`). We run ``run_evaluation`` under a pinned
  ``swebench==<pin>`` venv from a **non-shadowing** cwd (a fresh temp dir, so the
  local ``swebench/`` package can't shadow the installed one), exchanging files
  (``predictions.jsonl`` in, ``report.json`` out).
* The official runner reuses already-pulled images (our :mod:`image_store`
  cache) under ``--namespace swebench --cache_level instance`` — no re-pull.

Public API:

* :func:`ensure_official_venv` — path to the pinned official-swebench venv python,
  built **concurrency-safely** (atomic tmp-build + rename, plus an import-readiness
  check). This folds in the #353 TOCTOU fix.
* :func:`grade_predictions` — grade a batch of predictions, returns
  ``{instance_id: {resolved, patch_successfully_applied, tests_status, ...}}``.
* :func:`grade_one` — single-instance convenience wrapper.

Network + an ``HF_TOKEN`` in ``os.environ`` and a reachable Docker daemon are
required at grade time (inherited from the parent environment; never hardcoded).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

#: Pin must match ``scripts/extract_swebench_specs.py`` / ``official_grade`` (the
#: specs vendored from the same release). A different upstream release can parse
#: or grade differently, so it is pinned.
PINNED_SWEBENCH = "swebench==4.1.0"

#: Default model id written into predictions when not supplied. ``run_evaluation``
#: keys its per-instance log tree under this name.
DEFAULT_MODEL_NAME = "onlycodes"

#: Default canonical dataset — keeps test_patch / FAIL_TO_PASS / PASS_TO_PASS
#: from ever drifting from official.
DEFAULT_DATASET = "princeton-nlp/SWE-bench_Verified"


class GradingError(RuntimeError):
    """Verbatim grading could not run (venv unusable, or the official
    ``run_evaluation`` subprocess failed catastrophically with no per-instance
    reports). A single bad instance never raises — it gets an error record."""


# --------------------------------------------------------------------------
# Official swebench venv (concurrency-safe; the #353 TOCTOU fix)
# --------------------------------------------------------------------------

def _default_venv_dir() -> Path:
    root = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(root) / "onlycodes" / "swe-official-venv"


def _venv_python(venv_dir: Path) -> Path:
    return venv_dir / "bin" / "python"


def _import_ready(py: Path | str) -> bool:
    """True iff ``<py> -c "import swebench"`` exits 0 — the venv is fully built.

    ``python -m venv`` creates ``bin/python`` *before* the slow
    ``pip install swebench`` finishes, so file-existence alone races a concurrent
    builder (#353). The only honest readiness signal is that ``swebench`` actually
    imports."""
    if not Path(py).is_file():
        return False
    try:
        proc = subprocess.run(
            [str(py), "-c", "import swebench"],
            capture_output=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _build_venv_atomic(venv_dir: Path) -> None:
    """Build the venv into a sibling temp dir and ``os.replace`` it into place.

    The rename is atomic, so ``venv_dir`` never exists half-built: a concurrent
    caller sees either no venv or a complete, import-ready one. The temp suffix is
    derived from the pid (deterministic per process; not time/random based) so
    parallel workers don't collide. If another process won the race and produced a
    ready venv first, we keep theirs and discard our build."""
    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = venv_dir.with_name(f"{venv_dir.name}.{os.getpid()}.tmp")
    if tmp_dir.exists():
        _rmtree_quiet(tmp_dir)
    try:
        subprocess.run([sys.executable, "-m", "venv", str(tmp_dir)],
                       check=True, capture_output=True)
        subprocess.run([str(_venv_python(tmp_dir)), "-m", "pip", "install",
                        "-q", PINNED_SWEBENCH], check=True)
        if not _import_ready(_venv_python(tmp_dir)):
            raise GradingError(
                f"built venv at {tmp_dir} but 'import swebench' failed after install")
        try:
            os.replace(tmp_dir, venv_dir)
        except OSError:
            # A concurrent builder already populated venv_dir (rename onto a
            # non-empty dir fails). If theirs is ready, take it; else re-raise.
            if not _import_ready(_venv_python(venv_dir)):
                raise
    except subprocess.CalledProcessError as e:
        out = (e.stderr or b"").decode("utf-8", "replace")[:500]
        raise GradingError(f"building official swebench venv failed: {out}") from e
    finally:
        _rmtree_quiet(tmp_dir)


def _rmtree_quiet(path: Path) -> None:
    import shutil
    try:
        shutil.rmtree(path)
    except OSError:
        pass


def ensure_official_venv(*, create: bool = True) -> str:
    """Return the python of an isolated venv with ``PINNED_SWEBENCH`` installed.

    Resolution order:

    1. ``ONLYCODES_SWEBENCH_VENV`` — a venv directory or a python path. Used
       as-is (never modified); raises if it doesn't look usable.
    2. A cached venv under ``~/.cache/onlycodes/swe-official-venv``; built on
       first use when ``create`` (pip-installs the pin — heavy, but once).

    **Concurrency-safe (#353 fix).** Readiness is judged by ``import swebench``
    actually succeeding, never by ``bin/python`` merely existing (``venv`` creates
    that before ``pip install`` finishes). When a (re)build is needed it goes into
    a pid-suffixed sibling temp dir and is ``os.replace``-d into the final path, so
    the final path is never observed half-built.

    Set ``create=False`` (e.g. in CI/hermetic contexts) to require a
    pre-provisioned venv and never pip-install.
    """
    override = os.environ.get("ONLYCODES_SWEBENCH_VENV")
    if override:
        p = Path(override)
        cand = p if p.name == "python" or p.suffix else _venv_python(p)
        if cand.is_file():
            return str(cand)
        raise GradingError(
            f"ONLYCODES_SWEBENCH_VENV={override!r} is not a usable venv/python")

    venv_dir = _default_venv_dir()
    py = _venv_python(venv_dir)
    if _import_ready(py):
        return str(py)
    if not create:
        raise GradingError(
            f"official swebench venv at {venv_dir} is missing or not import-ready "
            "and create=False; set ONLYCODES_SWEBENCH_VENV or pre-build it")

    _build_venv_atomic(venv_dir)
    return str(_venv_python(venv_dir))


# --------------------------------------------------------------------------
# Report parsing (pure helper — unit-testable without docker)
# --------------------------------------------------------------------------

def _collect_reports(
    cwd: Path | str,
    run_id: str,
    model_name: str,
    instance_ids: list[str],
) -> dict[str, dict]:
    """Read per-instance ``report.json`` files under a ``run_evaluation`` log tree.

    Each report lives at
    ``<cwd>/logs/run_evaluation/<run_id>/<model_name>/<iid>/report.json`` and is
    shaped ``{"<iid>": {"resolved": bool, "patch_successfully_applied": bool,
    "tests_status": {...}}}``. Returns ``{iid: {...}}`` for every requested id;
    an instance whose report is missing or unreadable gets
    ``{"resolved": False, "error": "<reason>"}`` (never raises for one instance).
    """
    base = Path(cwd) / "logs" / "run_evaluation" / run_id / model_name
    out: dict[str, dict] = {}
    for iid in instance_ids:
        report_path = base / iid / "report.json"
        if not report_path.is_file():
            out[iid] = {"resolved": False,
                        "error": f"no report.json at {report_path}"}
            continue
        try:
            data = json.loads(report_path.read_text())
        except (OSError, json.JSONDecodeError) as e:
            out[iid] = {"resolved": False,
                        "error": f"unreadable report.json: {e}"}
            continue
        # The report nests under the instance id; tolerate a flat shape too.
        entry = data.get(iid, data)
        out[iid] = {
            "resolved": bool(entry.get("resolved", False)),
            "patch_successfully_applied": bool(
                entry.get("patch_successfully_applied", False)),
            "tests_status": entry.get("tests_status", {}),
        }
    return out


# --------------------------------------------------------------------------
# Grading
# --------------------------------------------------------------------------

def grade_predictions(
    predictions: list[dict],
    *,
    run_id: str,
    dataset_name: str = DEFAULT_DATASET,
    namespace: str = "swebench",
    instance_ids: list[str] | None = None,
    max_workers: int = 1,
    cache_level: str = "instance",
    model_name: str = DEFAULT_MODEL_NAME,
) -> dict[str, dict]:
    """Grade ``predictions`` verbatim through official ``run_evaluation``.

    ``predictions`` is a list of ``{"instance_id", "model_patch"}`` dicts;
    ``model_name_or_path`` is added as ``model_name`` when missing. Predictions are
    written to a temp ``predictions.jsonl`` and ``run_evaluation`` is invoked as a
    subprocess under :func:`ensure_official_venv`'s python, with ``cwd`` set to a
    fresh temp dir (so the local ``swebench/`` package can't shadow the installed
    one and all outputs are isolated). ``os.environ`` is inherited so the official
    runner sees ``HF_TOKEN`` and the docker socket.

    Returns ``{instance_id: {"resolved", "patch_successfully_applied",
    "tests_status"}}``. An instance that produced no report gets
    ``{"resolved": False, "error": ...}`` instead of aborting the batch. Raises
    :class:`GradingError` only if the subprocess failed catastrophically *and* no
    per-instance reports were produced at all.
    """
    if not predictions:
        raise GradingError("no predictions to grade")

    preds = []
    for p in predictions:
        iid = p.get("instance_id")
        if not iid:
            raise GradingError(f"prediction missing instance_id: {p!r}")
        preds.append({
            "instance_id": iid,
            "model_name_or_path": p.get("model_name_or_path", model_name),
            "model_patch": p.get("model_patch", ""),
        })

    ids = instance_ids if instance_ids is not None else [p["instance_id"] for p in preds]
    py = ensure_official_venv()

    work = Path(tempfile.mkdtemp(prefix="grade_"))
    preds_path = work / "predictions.jsonl"
    preds_path.write_text("".join(json.dumps(p) + "\n" for p in preds))

    cmd = [
        py, "-m", "swebench.harness.run_evaluation",
        "--dataset_name", dataset_name,
        "--predictions_path", str(preds_path),
        "--run_id", run_id,
        "--namespace", namespace,
        "--cache_level", cache_level,
        "--max_workers", str(max_workers),
        "--instance_ids", *ids,
    ]
    proc = subprocess.run(
        cmd, cwd=str(work), env=os.environ.copy(),
        capture_output=True, text=True,
    )

    reports = _collect_reports(work, run_id, model_name, ids)
    any_report = any("error" not in r for r in reports.values())
    if proc.returncode != 0 and not any_report:
        tail = (proc.stderr or proc.stdout or "")[-1500:]
        raise GradingError(
            f"run_evaluation failed (exit {proc.returncode}) with no per-instance "
            f"reports.\nstderr/stdout tail:\n{tail}")
    return reports


def grade_one(instance_id: str, model_patch: str, **kwargs) -> dict:
    """Grade a single instance verbatim; returns its report dict.

    Convenience wrapper over :func:`grade_predictions` for smoke / validation /
    drift triage. Extra keyword args (``dataset_name``, ``namespace``,
    ``cache_level``, ``model_name``, ``max_workers``) are forwarded.
    """
    return grade_predictions(
        [{"instance_id": instance_id, "model_patch": model_patch}],
        run_id=f"gradeone_{instance_id}",
        instance_ids=[instance_id],
        **kwargs,
    )[instance_id]
