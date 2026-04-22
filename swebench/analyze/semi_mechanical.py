"""Semi-mechanical pathology detection — Stage 1.5.

This module sits between Stage 1 (mechanical extraction) and Stage 2 (full
transcript subagent review). The motivation: many pathologies have a
detectable mechanical signal (e.g. ``git log --all`` + ``git show <hash>``
for ``reference_solution_lookup``) that can drastically narrow what the
LLM needs to see. Rather than feeding the full compressed transcript to
Stage 2, we extract only the matching turns and feed them to a focused
LLM reviewer.

Architecture
------------

The core surface is an **extractor registry**: each extractor is a triple
``(extractor_id, target_pattern_id, filter_fn, system_prompt)`` registered
via :func:`register`. The stage driver iterates every (log × extractor)
pair; extractors whose ``filter_fn`` returns a non-empty list of excerpts
are fed to ``claude -p`` with their own system prompt. Matches produce
sidecar JSON under ``<analysis_root>/semi_mechanical/<log_ref>__<extractor_id>.json``
in the same schema as Stage 2 (validates via
:func:`swebench.analyze.registry.validate_subagent_output`).

Extractors can be added by creating a new file under
``swebench/analyze/extractors/`` and calling :func:`register` at import
time. The ``extractors`` subpackage's ``__init__`` imports all bundled
extractors to trigger their registration. No changes to ``run.py`` or
this module are required when adding an extractor.

Stage 2 skip gating
-------------------

:func:`run_semi_mechanical` returns the set of ``log_ref`` values that
matched at least one extractor. The caller (``run.py``) passes this set
to ``_stage_subagents`` so those logs are dropped from full-transcript
review — semi-mechanical supersedes Stage 2 for that log.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import click

from swebench.analyze import registry
from swebench.harness import find_claude_binary, make_isolated_claude_config


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


#: A mechanical-filter callable: takes a JSONL path, returns a list of
#: human-readable excerpt strings. Empty list means "this extractor does
#: not apply to this log".
FilterFn = Callable[[Path], list[str]]


@dataclass(frozen=True)
class Extractor:
    """A registered semi-mechanical extractor."""

    extractor_id: str
    target_pattern_id: str
    filter_fn: FilterFn
    system_prompt: str


_REGISTRY: dict[str, Extractor] = {}
_REGISTRY_LOCK = threading.Lock()


def register(
    extractor_id: str,
    *,
    target_pattern_id: str,
    filter_fn: FilterFn,
    system_prompt: str,
) -> None:
    """Register an extractor. Call from module top-level at import time.

    Raises :class:`ValueError` if ``extractor_id`` is already registered —
    duplicate registrations indicate a typo or an import-order bug.
    """
    with _REGISTRY_LOCK:
        if extractor_id in _REGISTRY:
            raise ValueError(f"extractor {extractor_id!r} already registered")
        _REGISTRY[extractor_id] = Extractor(
            extractor_id=extractor_id,
            target_pattern_id=target_pattern_id,
            filter_fn=filter_fn,
            system_prompt=system_prompt,
        )


def iter_extractors() -> Iterator[Extractor]:
    """Yield registered extractors in registration order."""
    with _REGISTRY_LOCK:
        snapshot = list(_REGISTRY.values())
    yield from snapshot


def _reset_registry_for_testing() -> None:
    """Clear the extractor registry. Tests only — production code never calls this."""
    with _REGISTRY_LOCK:
        _REGISTRY.clear()


# ---------------------------------------------------------------------------
# Concurrency primitive (same style as run.py)
# ---------------------------------------------------------------------------


_print_lock = threading.Lock()


def _echo(msg: str, *, err: bool = False) -> None:
    with _print_lock:
        click.echo(msg, err=err)


# ---------------------------------------------------------------------------
# Stage driver
# ---------------------------------------------------------------------------


#: Dry-run preview cap on excerpt body (characters per extractor output).
DRY_RUN_EXCERPT_PREVIEW_CHARS = 400


def _build_user_prompt(log_ref: str, arm: str, excerpts: list[str]) -> str:
    """Build the user prompt for a semi-mechanical reviewer."""
    body = "\n\n".join(f"--- Excerpt {i + 1} ---\n{ex}" for i, ex in enumerate(excerpts))
    return (
        f"log_ref: {log_ref}\n"
        f"arm: {arm}\n"
        f"extractor matched {len(excerpts)} turn(s)\n\n"
        f"{body}\n"
    )


def _compose_cmd(claude_binary: str, system_prompt: str) -> list[str]:
    """Compose the ``claude -p`` command for a semi-mechanical reviewer."""
    return [
        claude_binary,
        "-p",
        "--system-prompt", system_prompt,
        "--allowedTools", "",
        "--dangerously-skip-permissions",
        "--no-session-persistence",
        "--output-format", "text",
    ]


def _parse_reviewer_reply(raw: str) -> dict | None:
    """Parse a reviewer's JSON reply, stripping markdown code fences if present."""
    import re as _re
    s = raw.strip()
    s = _re.sub(r"^```(?:json)?\s*", "", s)
    s = _re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return None


def _reviewer_to_sidecar(
    *,
    log_ref: str,
    arm: str,
    extractor: Extractor,
    reviewer: dict,
    excerpts: list[str],
) -> dict:
    """Convert a reviewer's reply into a sidecar dict that passes ``validate_subagent_output``.

    The reviewer is free-form (flagged / reasoning / evidence) — we shape
    it into the subagent-output schema so Stage 3 can ingest it uniformly.
    """
    flagged = bool(reviewer.get("flagged", False))
    confidence = str(reviewer.get("confidence", "low")).lower()
    if confidence not in ("low", "medium", "high"):
        confidence = "low"
    reasoning = str(reviewer.get("reasoning", ""))

    findings: list[dict] = []
    if flagged:
        evidence_items = reviewer.get("key_evidence") or []
        if not isinstance(evidence_items, list):
            evidence_items = [str(evidence_items)]
        evidence_refs = [
            {"excerpt": str(ev)[:500]} for ev in evidence_items[:8]
        ]
        if not evidence_refs and excerpts:
            evidence_refs = [{"excerpt": excerpts[0][:500]}]
        # Severity mirrors the reviewer's confidence — the two enums align
        # (low/medium/high) and this preserves the reviewer's strength signal
        # for Stage 3. Hard-coding "medium" would flatten high-confidence
        # flags into the same bucket as low-confidence ones.
        findings.append({
            "candidate_id": extractor.target_pattern_id,
            "description": reasoning or f"Flagged by {extractor.extractor_id}",
            "evidence_refs": evidence_refs,
            "severity": confidence,
            "confidence": confidence,
        })

    return {
        "log_ref": log_ref,
        "arm": arm,
        "findings": findings,
        "notes": f"semi-mechanical:{extractor.extractor_id} flagged={flagged}",
    }


def _run_one(
    *,
    metric: dict,
    extractor: Extractor,
    out_dir: Path,
    claude_binary: str | None,
    force: bool,
    dry_run: bool,
) -> tuple[str, str, bool, bool, str]:
    """Run a single (log × extractor) pair.

    Returns ``(log_ref, extractor_id, matched, flagged, message)``.
    ``matched`` = the mechanical filter returned ≥1 excerpt.
    ``flagged`` = the reviewer (or dry-run marker) decided the pathology fires.
    """
    log_ref = metric["log_ref"]
    arm = metric.get("arm") or "unknown"
    jsonl_path = Path(metric["jsonl_path"])

    try:
        excerpts = extractor.filter_fn(jsonl_path)
    except Exception as exc:  # noqa: BLE001 — filter surface is broad
        return (log_ref, extractor.extractor_id, False, False,
                f"filter error: {type(exc).__name__}: {exc}")

    if not excerpts:
        return (log_ref, extractor.extractor_id, False, False, "no match")

    sidecar = out_dir / f"{log_ref}__{extractor.extractor_id}.json"
    if sidecar.exists() and not force and not dry_run:
        return (log_ref, extractor.extractor_id, True, True, "skipped (cached)")

    user_prompt = _build_user_prompt(log_ref, arm, excerpts)

    if dry_run:
        binary_display = claude_binary or "<claude>"
        cmd = _compose_cmd(binary_display, extractor.system_prompt)
        preview = user_prompt[:DRY_RUN_EXCERPT_PREVIEW_CHARS]
        import shlex
        _echo(
            f"--- DRY RUN semi-mechanical: {log_ref} ---\n"
            f"extractor={extractor.extractor_id} target={extractor.target_pattern_id}\n"
            f"arm={arm}\n"
            f"sidecar: {sidecar}\n"
            f"cmd: {' '.join(shlex.quote(p) for p in cmd[:6])} ...\n"
            f"prompt preview (first {DRY_RUN_EXCERPT_PREVIEW_CHARS} chars):\n"
            f"{preview}\n"
            f"--- /DRY RUN ---"
        )
        return (log_ref, extractor.extractor_id, True, True, "dry-run")

    assert claude_binary is not None
    cmd = _compose_cmd(claude_binary, extractor.system_prompt)
    cfg_dir = make_isolated_claude_config()
    try:
        env = {**os.environ, "CLAUDE_CONFIG_DIR": cfg_dir}
        proc = subprocess.run(cmd, input=user_prompt, capture_output=True, text=True, env=env)
    finally:
        shutil.rmtree(cfg_dir, ignore_errors=True)

    if proc.returncode != 0:
        return (log_ref, extractor.extractor_id, True, False,
                f"claude exit {proc.returncode}: {proc.stderr.strip()[:300]}")

    reviewer = _parse_reviewer_reply(proc.stdout)
    if reviewer is None:
        return (log_ref, extractor.extractor_id, True, False,
                "reviewer output not valid JSON")

    sidecar_data = _reviewer_to_sidecar(
        log_ref=log_ref, arm=arm, extractor=extractor,
        reviewer=reviewer, excerpts=excerpts,
    )
    errs = registry.validate_subagent_output(sidecar_data)
    if errs:
        return (log_ref, extractor.extractor_id, True, False,
                f"sidecar failed validation: {'; '.join(errs[:3])}")

    sidecar.write_text(json.dumps(sidecar_data, indent=2, sort_keys=True))
    flagged = bool(sidecar_data["findings"])
    return (log_ref, extractor.extractor_id, True, flagged, str(sidecar))


def run_semi_mechanical(
    *,
    metrics: list[dict],
    analysis_root: Path,
    concurrency: int,
    force: bool,
    dry_run: bool,
) -> set[str]:
    """Run every registered extractor against every log in ``metrics``.

    Returns the set of ``log_ref`` values that had at least one extractor
    produce a sidecar with non-empty findings (i.e. flagged). The caller
    uses this set to skip those logs in Stage 2.

    If no extractors are registered, this is a no-op and returns an empty
    set (logs may have been discovered but nothing to run against).
    """
    extractors = list(iter_extractors())
    if not extractors:
        _echo("[semi-mechanical] no extractors registered; skipping stage.")
        return set()
    if not metrics:
        _echo("[semi-mechanical] no logs; nothing to do.")
        return set()

    out_dir = analysis_root / "semi_mechanical"
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    # claude binary only needed if any extractor actually matches a log.
    # In dry-run we tolerate its absence (nothing will be invoked). Outside
    # dry-run we require it up-front: deferring the error until a worker
    # thread hits `assert claude_binary is not None` would surface as an
    # unhelpful AssertionError, after partial sidecars may already be on disk.
    claude_binary: str | None
    try:
        claude_binary = find_claude_binary()
    except FileNotFoundError:
        claude_binary = None
    if not dry_run and claude_binary is None:
        raise click.UsageError(
            "claude binary not found on PATH; install it or re-run with --dry-run"
        )

    flagged_refs: set[str] = set()
    matched_count = 0
    flagged_count = 0
    error_count = 0

    pairs = [(m, ex) for m in metrics for ex in extractors]

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = {
            pool.submit(
                _run_one,
                metric=m,
                extractor=ex,
                out_dir=out_dir,
                claude_binary=claude_binary,
                force=force,
                dry_run=dry_run,
            ): (m["log_ref"], ex.extractor_id)
            for m, ex in pairs
        }
        for fut in as_completed(futs):
            log_ref, ex_id, matched, flagged, msg = fut.result()
            if matched:
                matched_count += 1
                if flagged:
                    flagged_count += 1
                    flagged_refs.add(log_ref)
                    _echo(f"[semi-mechanical] FLAG {log_ref} × {ex_id}: {msg}")
                else:
                    if msg.startswith(("claude exit", "reviewer output", "sidecar failed")):
                        error_count += 1
                        _echo(f"[semi-mechanical] ERR  {log_ref} × {ex_id}: {msg}", err=True)
                    else:
                        _echo(f"[semi-mechanical] OK   {log_ref} × {ex_id}: {msg}")

    _echo(
        f"[semi-mechanical] summary: matched={matched_count} flagged={flagged_count} "
        f"errors={error_count} logs_skipped_by_stage2={len(flagged_refs)}"
    )
    return flagged_refs


# ---------------------------------------------------------------------------
# Bundled extractors — auto-import on first call
# ---------------------------------------------------------------------------


_BUNDLED_LOADED = False
_BUNDLED_LOAD_LOCK = threading.Lock()


def load_bundled_extractors() -> None:
    """Import the ``swebench.analyze.extractors`` subpackage so its
    ``register()`` calls run. Idempotent and thread-safe."""
    global _BUNDLED_LOADED
    with _BUNDLED_LOAD_LOCK:
        if _BUNDLED_LOADED:
            return
        # Import for side-effects (each extractor module calls register()).
        import swebench.analyze.extractors  # noqa: F401
        _BUNDLED_LOADED = True


def _reset_bundled_for_testing() -> None:
    """Clear the bundled-loader latch and purge cached extractor modules.

    Tests only — production code never calls this. Pair with
    :func:`_reset_registry_for_testing` when a test needs to exercise the
    bundled-extractor registration path more than once within a process.
    """
    import sys as _sys
    global _BUNDLED_LOADED
    with _BUNDLED_LOAD_LOCK:
        _BUNDLED_LOADED = False
        for modname in list(_sys.modules):
            if modname.startswith("swebench.analyze.extractors"):
                del _sys.modules[modname]


__all__ = [
    "Extractor",
    "FilterFn",
    "register",
    "iter_extractors",
    "load_bundled_extractors",
    "run_semi_mechanical",
    "_reset_bundled_for_testing",
    "_reset_registry_for_testing",
]
