"""Stage 2b runner — fan out per-log subagents over compressed transcripts.

Pipeline overview (epic #62):

- **Stage 1 (mechanical).** For every ``*_run*.jsonl`` under ``--results-dir``,
  call :func:`swebench.analyze.extractor.extract` and persist the result as a
  sidecar JSON under ``runs/swebench/_analysis/<run_id>/mechanical/``.
  Produce a ``triage.json`` listing the top ``TRIAGE_TOP_PERCENTILE`` of runs
  (via :func:`swebench.analyze.extractor.triage_rank`) — those are the ones
  fed to Stage 2.
- **Stage 2 (subagents).** For each log flagged by triage, compose a
  ``claude -p`` command using :func:`swebench.harness.find_claude_binary` and
  :func:`swebench.harness.make_isolated_claude_config`, compressed log body +
  the system prompt at ``subagent_prompt.md``. Write the subagent's JSON reply
  to ``runs/swebench/_analysis/<run_id>/subagents/<log_ref>.json``.
  Parallel fan-out follows the ``swebench/add.py`` template: ``_print_lock``
  serialises ``click.echo`` and ``_process_one`` returns ``(id, ok, msg)``.
- **Stage 3 (synthesize).** Read every Stage 2 subagent sidecar, pass the
  full set plus the current ``patterns.json`` to a single synthesizer
  ``claude -p`` invocation, then merge its output into the registry via
  :func:`swebench.analyze.registry.merge` + atomic write.

All stages are idempotent: runs whose sidecar JSON already exists are skipped
unless ``--force`` is passed. ``--dry-run`` prints the composed commands and
prompts without invoking ``claude`` (fully offline-testable).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import click

from swebench import repo_root
from swebench.analyze import registry
from swebench.analyze.compress import compress
from swebench.analyze.extractor import extract, triage_rank
from swebench.harness import find_claude_binary, make_isolated_claude_config


# ---------------------------------------------------------------------------
# Concurrency primitives (mirror swebench/add.py)
# ---------------------------------------------------------------------------


_print_lock = threading.Lock()


def _echo(msg: str, *, err: bool = False) -> None:
    with _print_lock:
        click.echo(msg, err=err)


# ---------------------------------------------------------------------------
# Path + naming helpers
# ---------------------------------------------------------------------------


#: Regex to split a run filename stem into (instance_id, arm, run_idx).
#: SWE-bench layout: ``runs/swebench/<instance>_<arm>_run<N>.jsonl``.
_RUN_STEM_RE = re.compile(r"^(?P<instance>.+)_(?P<arm>baseline|onlycode)_run(?P<run>\d+)$")

#: Valid artifact-arm directory names (matches ``VALID_ARMS`` in registry.py).
_ARTIFACT_ARMS = ("tool_rich", "code_only")

#: Regex for the artifact run-directory name (``run<N>``).
_ARTIFACT_RUN_DIR_RE = re.compile(r"^run(?P<run>\d+)$")


def _default_run_id() -> str:
    """Return a compact UTC timestamp ``YYYYMMDDTHHMMSSZ`` for this invocation."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _discover_logs(results_dir: Path) -> list[Path]:
    """Return sorted run-JSONL files under ``results_dir``.

    Supports two layouts:

    - **SWE-bench** (flat): ``<results_dir>/*_<arm>_run<N>.jsonl``.
    - **Artifact** (nested, depth-3): ``<results_dir>/<task>/<arm>/run<N>/agent.jsonl``
      where ``arm`` is ``tool_rich`` or ``code_only``.

    Both layouts may coexist under the same ``results_dir`` — returned list
    is the union, sorted by path. Any subtree under ``_analysis/`` is
    excluded (that's where sidecars live).
    """
    flat = sorted(results_dir.glob("*_run*.jsonl"))

    artifact: list[Path] = []
    for task_dir in sorted(results_dir.iterdir()) if results_dir.is_dir() else []:
        if not task_dir.is_dir() or task_dir.name.startswith("_"):
            continue
        for arm in _ARTIFACT_ARMS:
            arm_dir = task_dir / arm
            if not arm_dir.is_dir():
                continue
            for run_dir in sorted(arm_dir.iterdir()):
                if not run_dir.is_dir():
                    continue
                if not _ARTIFACT_RUN_DIR_RE.match(run_dir.name):
                    continue
                agent = run_dir / "agent.jsonl"
                if agent.is_file():
                    artifact.append(agent)

    # flat and artifact cannot overlap (flat yields *_run*.jsonl at depth 1;
    # artifact yields agent.jsonl at depth 4), so no dedup set needed.
    return sorted(flat + artifact)


def _parse_log_ref(jsonl_path: Path) -> tuple[str, str, int] | None:
    """Return ``(instance_id, arm, run_idx)`` for a run JSONL, or None if unparseable.

    Handles both SWE-bench flat filenames and nested artifact layout
    (``<task>/<arm>/run<N>/agent.jsonl``).
    """
    # SWE-bench flat filename first.
    m = _RUN_STEM_RE.match(jsonl_path.stem)
    if m:
        return m.group("instance"), m.group("arm"), int(m.group("run"))

    # Artifact nested layout: <task>/<arm>/run<N>/agent.jsonl
    if jsonl_path.name == "agent.jsonl":
        parts = jsonl_path.parts
        if len(parts) >= 4:
            run_name = parts[-2]
            arm = parts[-3]
            task = parts[-4]
            # Skip paths rooted under an _analysis-style subtree — mirrors
            # the exclusion rule in _discover_logs so that a manually-passed
            # sidecar path does not accidentally parse as a real artifact log.
            if task.startswith("_"):
                return None
            run_m = _ARTIFACT_RUN_DIR_RE.match(run_name)
            if arm in _ARTIFACT_ARMS and run_m:
                return task, arm, int(run_m.group("run"))
    return None


def _synthesize_log_ref(parsed: tuple[str, str, int] | None, jsonl_path: Path) -> str:
    """Return a stable, unique ``log_ref`` string for a JSONL path.

    For artifact logs whose filename stem is always ``agent`` (non-unique),
    the synthesized form is ``<task>__<arm>__run<N>``. For SWE-bench logs
    the existing filename stem is already unique.

    .. note::
       The returned ``log_ref`` is treated as an **opaque identifier** by
       downstream consumers. Do **not** re-parse it by splitting on ``__``:
       artifact task IDs themselves contain ``__`` (per the
       ``<category>__<slug>`` convention in ``docs/SCHEMA_ARTIFACT.md``), so
       the final form has four ``__``-delimited fields, not three. To recover
       ``(task, arm, run)`` from a log, call :func:`_parse_log_ref` on the
       original JSONL path — never split the synthesized ``log_ref``.
    """
    if parsed is None:
        return jsonl_path.stem
    instance, arm, run = parsed
    # SWE-bench: the stem is already unique and historically used as log_ref.
    if jsonl_path.stem != "agent":
        return jsonl_path.stem
    # Artifact: synthesize.
    return f"{instance}__{arm}__run{run}"


def _analysis_root(results_dir: Path, run_id: str) -> Path:
    """Return ``<results_dir>/_analysis/<run_id>/`` (created lazily by callers)."""
    return results_dir / "_analysis" / run_id


# ---------------------------------------------------------------------------
# Stage 1: mechanical
# ---------------------------------------------------------------------------


def _stage_mechanical(
    *,
    logs: list[Path],
    analysis_root: Path,
    force: bool,
    dry_run: bool,
) -> list[dict]:
    """Run the mechanical extractor on every log, write sidecars, return metrics.

    Returns a list of per-log metric dicts (extended with ``task_id``, ``arm``,
    ``run``, and ``log_ref`` for downstream consumers). In ``--dry-run`` mode
    nothing is written to disk; the metrics are still computed in-memory so
    triage can run.
    """
    mech_dir = analysis_root / "mechanical"
    if not dry_run:
        mech_dir.mkdir(parents=True, exist_ok=True)

    metrics: list[dict] = []
    for jsonl in logs:
        parsed = _parse_log_ref(jsonl)
        log_ref = _synthesize_log_ref(parsed, jsonl)
        sidecar = mech_dir / f"{log_ref}.json"

        if sidecar.exists() and not force and not dry_run:
            try:
                data = json.loads(sidecar.read_text())
                _echo(f"[stage1] skip (cached): {jsonl.name}")
            except (OSError, json.JSONDecodeError):
                data = extract(jsonl)
                sidecar.write_text(json.dumps(data, indent=2, sort_keys=True))
                _echo(f"[stage1] re-extracted (bad cache): {jsonl.name}")
        else:
            data = extract(jsonl)
            if not dry_run:
                sidecar.write_text(json.dumps(data, indent=2, sort_keys=True))
                _echo(f"[stage1] extracted: {jsonl.name}")
            else:
                _echo(f"[stage1] would extract: {jsonl.name}")

        if parsed is not None:
            instance, arm, run = parsed
            data["task_id"] = instance
            data["arm"] = arm
            data["run"] = run
        data["log_ref"] = log_ref
        data["jsonl_path"] = str(jsonl)
        metrics.append(data)
    return metrics


def _write_triage(
    *,
    metrics: list[dict],
    analysis_root: Path,
    dry_run: bool,
) -> list[dict]:
    """Run :func:`triage_rank` and persist ``triage.json``; return flagged subset.

    The "flagged subset" is the top :data:`TRIAGE_TOP_PERCENTILE` of ranked runs
    — i.e. everything whose priority tuple ranks it in the first bucket. For
    simplicity we slice the ranked list at ``ceil(len * TRIAGE_TOP_PERCENTILE)``,
    matching the docstring guarantee of "top 20% flagged".
    """
    from swebench.analyze.extractor import TRIAGE_TOP_PERCENTILE

    ranked = triage_rank(metrics)
    cutoff = max(1, int(round(len(ranked) * TRIAGE_TOP_PERCENTILE))) if ranked else 0
    flagged = ranked[:cutoff]

    payload = {
        "ranked": [
            {
                "log_ref": m.get("log_ref"),
                "task_id": m.get("task_id"),
                "arm": m.get("arm"),
                "run": m.get("run"),
                "turns": m.get("turns"),
                "total_cost_usd": m.get("total_cost_usd"),
                "mechanical_flags": m.get("mechanical_flags", []),
                "flagged": i < cutoff,
            }
            for i, m in enumerate(ranked)
        ],
        "cutoff_count": cutoff,
        "top_percentile": TRIAGE_TOP_PERCENTILE,
    }
    if not dry_run:
        (analysis_root / "triage.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True)
        )
        _echo(f"[triage] flagged {cutoff}/{len(ranked)} runs")
    else:
        _echo(f"[triage] would flag {cutoff}/{len(ranked)} runs")
    return flagged


# ---------------------------------------------------------------------------
# Stage 2: subagents
# ---------------------------------------------------------------------------


#: Path to the subagent system prompt, shipped alongside this module.
SUBAGENT_PROMPT_PATH = Path(__file__).parent / "subagent_prompt.md"

#: Dry-run preview cap on compressed log body (characters).
DRY_RUN_LOG_PREVIEW_CHARS = 200


def _read_subagent_prompt() -> str:
    """Read and return the subagent system prompt."""
    return SUBAGENT_PROMPT_PATH.read_text()


def _compose_claude_cmd(claude_binary: str, system_prompt: str) -> list[str]:
    """Compose the ``claude -p`` command for a single subagent invocation.

    The user prompt is passed via stdin to avoid ARG_MAX limits on large logs.
    We restrict the subagent to ``Read,Write`` (it doesn't need a shell); the
    system prompt is responsible for telling it to emit JSON only.
    """
    return [
        claude_binary,
        "-p",
        "--system-prompt", system_prompt,
        "--allowedTools", "Read,Write",
        "--dangerously-skip-permissions",
        "--no-session-persistence",
        "--output-format", "text",
    ]


def _build_user_prompt(log_ref: str, arm: str, compressed: str) -> str:
    """Build the user-facing prompt for one subagent."""
    return (
        f"log_ref: {log_ref}\n"
        f"arm: {arm}\n\n"
        f"## Compressed transcript\n\n"
        f"{compressed}\n"
    )


def _process_one(
    *,
    metric: dict,
    out_dir: Path,
    claude_binary: str | None,
    system_prompt: str,
    force: bool,
    dry_run: bool,
) -> tuple[str, bool, str]:
    """Run a single subagent end-to-end. Returns ``(log_ref, ok, message)``."""
    log_ref = metric.get("log_ref") or Path(metric["jsonl_path"]).stem
    sidecar = out_dir / f"{log_ref}.json"

    if sidecar.exists() and not force and not dry_run:
        return (log_ref, True, "skipped (cached)")

    try:
        compressed = compress(metric["jsonl_path"])
    except Exception as exc:  # noqa: BLE001 — compression surface is broad
        return (log_ref, False, f"compress failed: {type(exc).__name__}: {exc}")

    arm = metric.get("arm") or "unknown"
    user_prompt = _build_user_prompt(log_ref, arm, compressed)

    if dry_run:
        binary_display = claude_binary or "<claude>"
        cmd = _compose_claude_cmd(binary_display, system_prompt)
        preview = compressed[:DRY_RUN_LOG_PREVIEW_CHARS]
        _echo(
            f"--- DRY RUN: {log_ref} ---\n"
            f"sidecar: {sidecar}\n"
            f"cmd: {' '.join(_shlex_quote(p) for p in cmd[:6])} ...\n"
            f"compressed preview (first {DRY_RUN_LOG_PREVIEW_CHARS} chars):\n"
            f"{preview}\n"
            f"--- /DRY RUN ---"
        )
        return (log_ref, True, "dry-run")

    assert claude_binary is not None  # narrowed by caller
    cmd = _compose_claude_cmd(claude_binary, system_prompt)

    cfg_dir = make_isolated_claude_config()
    try:
        env = {"CLAUDE_CONFIG_DIR": cfg_dir}
        import os
        merged = {**os.environ, **env}
        proc = subprocess.run(
            cmd,
            input=user_prompt,
            capture_output=True,
            text=True,
            env=merged,
        )
        if proc.returncode != 0:
            return (
                log_ref,
                False,
                f"claude exit {proc.returncode}: {proc.stderr.strip()[:500]}",
            )
        sidecar.write_text(proc.stdout)
        return (log_ref, True, str(sidecar))
    finally:
        shutil.rmtree(cfg_dir, ignore_errors=True)


def _shlex_quote(part: str) -> str:
    """Quote a single arg for display (shlex.quote without importing twice)."""
    import shlex
    return shlex.quote(part)


def _stage_subagents(
    *,
    flagged: list[dict],
    analysis_root: Path,
    concurrency: int,
    force: bool,
    dry_run: bool,
    skip_log_refs: set[str] | None = None,
) -> tuple[int, int]:
    """Fan out subagents. Returns ``(succeeded, failed)`` counts.

    ``skip_log_refs``: if provided, any flagged log whose ``log_ref`` is in
    this set is skipped — the semi-mechanical stage already produced a
    sidecar for it, so running the full-transcript subagent would be
    redundant and expensive.
    """
    if skip_log_refs:
        before = len(flagged)
        flagged = [m for m in flagged if m.get("log_ref") not in skip_log_refs]
        skipped = before - len(flagged)
        if skipped:
            _echo(
                f"[stage2] skipping {skipped} log(s) already covered by "
                f"semi-mechanical extractors"
            )
    if not flagged:
        _echo("[stage2] no flagged runs; nothing to do.")
        return (0, 0)

    out_dir = analysis_root / "subagents"
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    system_prompt = _read_subagent_prompt()
    claude_binary: str | None
    if dry_run:
        # In dry-run we prefer to show the real path when available but do not
        # require the binary to be installed.
        try:
            claude_binary = find_claude_binary()
        except FileNotFoundError:
            claude_binary = None
    else:
        claude_binary = find_claude_binary()

    succ = 0
    fail = 0
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = {
            pool.submit(
                _process_one,
                metric=m,
                out_dir=out_dir,
                claude_binary=claude_binary,
                system_prompt=system_prompt,
                force=force,
                dry_run=dry_run,
            ): m
            for m in flagged
        }
        for fut in as_completed(futs):
            log_ref, ok, msg = fut.result()
            if ok:
                succ += 1
                _echo(f"[stage2] OK   {log_ref}: {msg}")
            else:
                fail += 1
                _echo(f"[stage2] FAIL {log_ref}: {msg}", err=True)
    return (succ, fail)


# ---------------------------------------------------------------------------
# Stage 3: synthesize
# ---------------------------------------------------------------------------


#: Path to the synthesizer system prompt, shipped alongside this module.
SYNTHESIZER_PROMPT_PATH = Path(__file__).parent / "synthesizer_prompt.md"

#: Dry-run preview cap on the synthesizer user prompt (characters).
DRY_RUN_SYNTH_PREVIEW_CHARS = 400


def _read_synthesizer_prompt() -> str:
    """Read and return the Stage 3 synthesizer system prompt."""
    return SYNTHESIZER_PROMPT_PATH.read_text()


def _collect_subagent_outputs(analysis_root: Path) -> list[dict]:
    """Load every valid subagent sidecar under ``analysis_root/subagents/``.

    Invalid or unparseable sidecars are logged via :func:`_echo` and skipped
    — one bad subagent reply must not block synthesis of the rest.
    """
    outputs: list[dict] = []
    # Load from both subagents/ (Stage 2 full-transcript) and
    # semi_mechanical/ (Stage 1.5 focused-excerpt) sidecar dirs. Both
    # produce subagent-shaped JSON and both validate via the same schema.
    for sub_dir_name in ("subagents", "semi_mechanical"):
        sub_dir = analysis_root / sub_dir_name
        if not sub_dir.is_dir():
            continue
        for sc in sorted(sub_dir.glob("*.json")):
            try:
                data = json.loads(sc.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                _echo(f"[stage3] skip unreadable sidecar {sc.name}: {exc}", err=True)
                continue
            errs = registry.validate_subagent_output(data)
            if errs:
                _echo(
                    f"[stage3] skip invalid sidecar {sub_dir_name}/{sc.name}: "
                    f"{'; '.join(errs[:3])}",
                    err=True,
                )
                continue
            outputs.append(data)
    return outputs


def _build_synth_user_prompt(
    existing_registry: dict, subagent_outputs: list[dict]
) -> str:
    """Build the user prompt for the synthesizer agent."""
    return (
        "## Current patterns.json\n\n"
        f"```json\n{json.dumps(existing_registry, indent=2, sort_keys=True)}\n```\n\n"
        "## Per-log subagent outputs\n\n"
        f"```json\n{json.dumps(subagent_outputs, indent=2, sort_keys=True)}\n```\n"
    )


def _compose_synth_cmd(claude_binary: str, system_prompt: str) -> list[str]:
    """Compose the ``claude -p`` command for the Stage 3 synthesizer.

    User prompt is passed via stdin to avoid ARG_MAX limits on large inputs.
    """
    return [
        claude_binary,
        "-p",
        "--system-prompt", system_prompt,
        "--allowedTools", "Read,Write",
        "--dangerously-skip-permissions",
        "--no-session-persistence",
        "--output-format", "text",
    ]


def _stage_synthesize(
    *,
    analysis_root: Path,
    run_id: str,
    patterns_path: Path,
    force: bool,
    dry_run: bool,
) -> tuple[bool, str]:
    """Synthesize per-log findings into ``patterns.json``.

    Returns ``(ok, message)``. Refuses to run on a malformed existing
    ``patterns.json`` unless ``force`` is set (ADR Q2).
    """
    outputs = _collect_subagent_outputs(analysis_root)
    _echo(f"[stage3] loaded {len(outputs)} subagent sidecar(s) for synthesis")

    # Load existing registry; refuse to run on malformed unless --force.
    if patterns_path.exists():
        data, err = registry.load_patterns(patterns_path)
        if err is not None and not force:
            msg = (
                f"patterns.json at {patterns_path} failed schema validation: "
                f"{err}. Re-run with --force to overwrite, or manually repair."
            )
            _echo(f"[stage3] ERROR: {msg}", err=True)
            return (False, msg)
        existing = data if data is not None else {"version": registry.SCHEMA_VERSION, "patterns": []}
    else:
        existing = {"version": registry.SCHEMA_VERSION, "patterns": []}

    system_prompt = _read_synthesizer_prompt()

    claude_binary: str | None
    if dry_run:
        try:
            claude_binary = find_claude_binary()
        except FileNotFoundError:
            claude_binary = None
    else:
        claude_binary = find_claude_binary()

    user_prompt = _build_synth_user_prompt(existing, outputs)

    if dry_run:
        binary_display = claude_binary or "<claude>"
        cmd = _compose_synth_cmd(binary_display, system_prompt)
        preview = user_prompt[:DRY_RUN_SYNTH_PREVIEW_CHARS]
        _echo(
            f"--- DRY RUN: stage3 synthesizer ---\n"
            f"patterns_path: {patterns_path}\n"
            f"run_id: {run_id}\n"
            f"subagent outputs: {len(outputs)}\n"
            f"cmd: {' '.join(_shlex_quote(p) for p in cmd[:6])} ...\n"
            f"user prompt preview (first {DRY_RUN_SYNTH_PREVIEW_CHARS} chars):\n"
            f"{preview}\n"
            f"--- /DRY RUN ---"
        )
        return (True, "dry-run")

    if not outputs:
        _echo("[stage3] no subagent outputs — skipping synthesizer call, registry unchanged.")
        return (True, "no outputs")

    assert claude_binary is not None
    cmd = _compose_synth_cmd(claude_binary, system_prompt)

    cfg_dir = make_isolated_claude_config()
    try:
        import os as _os
        merged_env = {**_os.environ, "CLAUDE_CONFIG_DIR": cfg_dir}
        proc = subprocess.run(cmd, input=user_prompt, capture_output=True, text=True, env=merged_env)
        if proc.returncode != 0:
            msg = f"synthesizer exit {proc.returncode}: {proc.stderr.strip()[:500]}"
            _echo(f"[stage3] ERROR: {msg}", err=True)
            return (False, msg)
        try:
            synth = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            msg = f"synthesizer output not valid JSON: {exc}"
            _echo(f"[stage3] ERROR: {msg}", err=True)
            # Persist raw output alongside for debugging.
            (analysis_root / "synthesizer_raw.txt").write_text(proc.stdout)
            return (False, msg)
    finally:
        shutil.rmtree(cfg_dir, ignore_errors=True)

    findings = synth.get("findings", []) if isinstance(synth, dict) else []
    if not isinstance(findings, list):
        msg = "synthesizer output missing 'findings' list"
        _echo(f"[stage3] ERROR: {msg}", err=True)
        return (False, msg)

    # Synthesizer findings have arm/log_ref inside each evidence_ref (since
    # one pattern aggregates across multiple logs). Fan them out into the
    # per-(log_ref, arm) shape that registry.merge() expects.
    flat_findings = registry.flatten_synth_findings(findings)
    merged = registry.merge(existing, flat_findings)
    errs = registry.validate(merged)
    if errs:
        msg = f"merged registry failed schema validation: {'; '.join(errs[:3])}"
        _echo(f"[stage3] ERROR: {msg}", err=True)
        return (False, msg)

    registry.write_patterns(patterns_path, merged)
    _echo(
        f"[stage3] wrote {patterns_path} "
        f"({len(merged['patterns'])} patterns after merge)"
    )
    return (True, str(patterns_path))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


STAGE_CHOICES = ("mechanical", "semi-mechanical", "subagents", "synthesize", "all")


def register_pathology_command(analyze_command: click.Group) -> None:
    """Attach the ``pathology`` subcommand to the parent ``analyze`` group."""

    @analyze_command.command("pathology")
    @click.option(
        "--results-dir",
        type=click.Path(exists=True, file_okay=False, path_type=Path),
        default=None,
        help=(
            "Path to results directory (default: runs/swebench/). "
            "Pass runs/artifact/ for the artifact benchmark; layouts "
            "(flat SWE-bench, nested <task>/<arm>/run<N>/agent.jsonl) are "
            "auto-detected."
        ),
    )
    @click.option(
        "--concurrency",
        type=int,
        default=8,
        show_default=True,
        help="Max parallel subagent invocations.",
    )
    @click.option(
        "--force",
        is_flag=True,
        default=False,
        help="Re-run stages even if sidecar JSON already exists.",
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        default=False,
        help="Print composed commands/prompts without invoking claude.",
    )
    @click.option(
        "--stage",
        type=click.Choice(STAGE_CHOICES),
        default="all",
        show_default=True,
        help="Which stage(s) to run.",
    )
    @click.option(
        "--run-id",
        "run_id",
        default=None,
        help="Identifier for this analysis run (default: UTC timestamp).",
    )
    def pathology_command(
        results_dir: Path | None,
        concurrency: int,
        force: bool,
        dry_run: bool,
        stage: str,
        run_id: str | None,
    ) -> None:
        """Run the log-analysis pipeline (stages 1, 2, and 3)."""
        if concurrency < 1:
            raise click.UsageError("--concurrency must be >= 1.")

        rdir = Path(results_dir) if results_dir else (repo_root() / "runs" / "swebench")
        if not rdir.is_dir():
            _echo(f"ERROR: results directory not found: {rdir}", err=True)
            sys.exit(1)

        rid = run_id or _default_run_id()
        aroot = _analysis_root(rdir, rid)
        if not dry_run:
            aroot.mkdir(parents=True, exist_ok=True)

        _echo(f"[pathology] results_dir={rdir}")
        _echo(f"[pathology] run_id={rid}")
        _echo(f"[pathology] analysis_root={aroot}")
        _echo(f"[pathology] stage={stage} concurrency={concurrency} "
              f"force={force} dry_run={dry_run}")

        logs = _discover_logs(rdir)
        if not logs:
            _echo(
                f"[pathology] no run JSONL files found under {rdir} "
                f"(looked for flat *_run*.jsonl and nested "
                f"<task>/<arm>/run<N>/agent.jsonl)"
            )
            return

        want_stage1 = stage in ("mechanical", "all")
        want_semi = stage in ("semi-mechanical", "all")
        want_stage2 = stage in ("subagents", "all")
        want_stage3 = stage in ("synthesize", "all")

        metrics: list[dict] = []
        flagged: list[dict] = []

        # Stage 1 metrics are needed by Stages 1.5 and 2.
        if want_stage1 or want_semi or want_stage2:
            metrics = _stage_mechanical(
                logs=logs,
                analysis_root=aroot,
                force=force,
                dry_run=dry_run,
            )
            flagged = _write_triage(
                metrics=metrics,
                analysis_root=aroot,
                dry_run=dry_run,
            )

        semi_matched: set[str] = set()
        if want_semi:
            # Late import to avoid pulling extractors into --help.
            from swebench.analyze.semi_mechanical import (
                load_bundled_extractors,
                run_semi_mechanical,
            )
            load_bundled_extractors()
            semi_matched = run_semi_mechanical(
                metrics=metrics,
                analysis_root=aroot,
                concurrency=concurrency,
                force=force,
                dry_run=dry_run,
            )

        if want_stage2:
            succ, fail = _stage_subagents(
                flagged=flagged,
                analysis_root=aroot,
                concurrency=concurrency,
                force=force,
                dry_run=dry_run,
                skip_log_refs=semi_matched,
            )
            _echo(f"[stage2] summary: ok={succ} fail={fail}")
            if fail:
                sys.exit(1)

        if want_stage3:
            patterns_path = repo_root() / "patterns.json"
            ok, msg = _stage_synthesize(
                analysis_root=aroot,
                run_id=rid,
                patterns_path=patterns_path,
                force=force,
                dry_run=dry_run,
            )
            if not ok:
                sys.exit(1)


__all__ = [
    "register_pathology_command",
    "SUBAGENT_PROMPT_PATH",
    "SYNTHESIZER_PROMPT_PATH",
    "STAGE_CHOICES",
]
