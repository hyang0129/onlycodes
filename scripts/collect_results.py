"""Collect SWE-bench and artifact results across all seed runs into a single CSV.

Walks every ``runs/swebench/full_run_seed_<N>[_codex_v2]/`` and
``runs/artifact/full_run_seed_<N>[_codex_v2]/`` directory, emits one row per
(instance_id, seed, agent, arm, run). Intended as the paper's source of truth
for cross-seed stats.

All per-LLM-call extraction is delegated to ``scripts/parse_run.py`` — this
module owns the directory walk, verdict resolution, and CSV layout only.

Usage:
    python scripts/collect_results.py [--out paper/data/all_results.csv]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path
from typing import Iterator

# Allow both ``python scripts/collect_results.py`` (script-mode, scripts/ on
# sys.path) and ``python -m scripts.collect_results`` (module-mode, repo root
# on sys.path). The directory has no __init__.py, so a bare ``import parse_run``
# is the form that works under both invocations once we put scripts/ on path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_run import RunResult, parse_run  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_SWEBENCH = REPO_ROOT / "runs" / "swebench"
RUNS_ARTIFACT = REPO_ROOT / "runs" / "artifact"
PROBLEMS_SWE = REPO_ROOT / "problems" / "swe"
PROBLEMS_ARTIFACT = REPO_ROOT / "problems" / "artifact"

# Recognise only the canonical paper-grade run dirs. Smoke/legacy/issue dirs
# are skipped — they aren't apples-to-apples with the seed sweeps.
RUN_DIR_RE = re.compile(r"^full_run_seed_(?P<seed>\d+)(?P<codex>_codex_v2)?$")

# SWE-bench result filename: <instance_id>_<arm>_run<N>_test.txt
TEST_FILE_RE = re.compile(
    r"^(?P<instance_id>.+)_(?P<arm>baseline|onlycode|bash_only)_run(?P<run>\d+)_test\.txt$"
)

FIELDNAMES = [
    "benchmark",            # swebench | artifact
    "dataset",              # swebench-verified-mini | swebench-datasci-mini | adhoc | <artifact-category>
    "instance_id",
    "seed",
    "agent",                # claude | codex
    "arm",
    "run",
    "verdict",              # PASS | FAIL | env_fail | ERROR
    "cost_usd",
    "num_turns",            # native agentic-loop count as the surface reports it.
                            # Claude: back-and-forth iterations. Codex: always 1 — codex wraps a
                            # run in a single "turn" containing many tool calls. Compare via
                            # tool_calls or llm_calls for cross-agent claims.
    "tool_calls",           # cross-agent: count of model-initiated tool invocations
                            # (Claude tool_use blocks ≈ Codex function_call + custom_tool_call).
    "llm_calls",            # cross-agent: count of model API calls
                            # (Claude assistant messages ≈ Codex token_count events).
    "wall_secs",
    "input_tokens",         # total prompt tokens INCLUDING cached, normalised across agents
                            # (Claude exposes input/cache_read/cache_creation separately; we sum
                            # them so the column matches codex's input_tokens convention).
    "cached_input_tokens",  # cache-read input tokens (Claude: cache_read_input_tokens;
                            # Codex: cached_input_tokens).
    "output_tokens",        # output tokens (Codex output_tokens already includes reasoning).
    "reasoning_tokens",     # codex-only (reasoning_output_tokens); None for Claude.
    "agent_surface",        # claude_code | codex_cli (from meta line; source of truth)
    "agent_version",
    "result_path",          # JSONL (swebench) or result.json (artifact)
]


# Datasets to exclude from the paper CSV. ``adhoc/`` holds developer-test
# fixtures that aren't part of the published mini sets and shouldn't appear
# in cross-seed stats.
EXCLUDED_DATASETS = {"adhoc"}


def _swebench_dataset_map() -> dict[str, str]:
    """Map ``instance_id`` -> name of the ``problems/swe/<dataset>/`` it lives in."""
    mapping: dict[str, str] = {}
    for yaml in PROBLEMS_SWE.glob("*/*.yaml"):
        mapping[yaml.stem] = yaml.parent.name
    return mapping


def _artifact_category(instance_id: str) -> str:
    """Artifact instance_ids have form ``<category>__<slug>``."""
    return instance_id.split("__", 1)[0]


def _run_dirs(root: Path) -> Iterator[tuple[Path, int, str]]:
    """Yield (dir, seed, agent) for each paper-grade run dir under *root*."""
    if not root.is_dir():
        return
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        m = RUN_DIR_RE.match(entry.name)
        if not m:
            continue
        seed = int(m.group("seed"))
        agent = "codex" if m.group("codex") else "claude"
        yield entry, seed, agent


def _empty_result() -> RunResult:
    return RunResult(
        surface=None, model=None, agent_version=None,
        cost_usd=None, num_turns=None, tool_calls=None, llm_calls=None,
        input_tokens=None, cached_input_tokens=None, output_tokens=None, reasoning_tokens=None,
        wall_secs=None,
    )


def _read_verdict(test_path: Path) -> str:
    try:
        lines = test_path.read_text().strip().splitlines()
    except OSError:
        return "ERROR"
    if not lines:
        return "ERROR"
    last = lines[-1].strip()
    if last not in ("PASS", "FAIL", "env_fail"):
        return "ERROR"
    # Retroactive classifier fix: post-#287 the harness wrote env_fail when
    # post-agent --collect-only returned 0 items, even though Phase 1 setup
    # had already validated the env. Treat those as FAIL — the agent failed
    # to keep the test tree importable, which is its job. (Forward fix is
    # in swebench/run.py.)
    if last == "env_fail":
        return "FAIL"
    return last


def _row_from_run(
    *, benchmark: str, dataset: str, instance_id: str, seed: int, agent: str,
    arm: str, run: int, verdict: str, jsonl: Path, result_path: Path,
    surface_default: str = "claude_code",
    agent_version_default: str | None = None,
) -> dict:
    rr = parse_run(jsonl) if jsonl.is_file() else _empty_result()
    return {
        "benchmark": benchmark,
        "dataset": dataset,
        "instance_id": instance_id,
        "seed": seed,
        "agent": agent,
        "arm": arm,
        "run": run,
        "verdict": verdict,
        "cost_usd": rr.cost_usd,
        "num_turns": rr.num_turns,
        "tool_calls": rr.tool_calls,
        "llm_calls": rr.llm_calls,
        "wall_secs": rr.wall_secs,
        "input_tokens": rr.input_tokens,
        "cached_input_tokens": rr.cached_input_tokens,
        "output_tokens": rr.output_tokens,
        "reasoning_tokens": rr.reasoning_tokens,
        "agent_surface": rr.surface or surface_default,
        "agent_version": rr.agent_version or agent_version_default,
        "result_path": str(result_path.relative_to(REPO_ROOT)),
    }


def collect_swebench(dataset_map: dict[str, str]) -> Iterator[dict]:
    for run_dir, seed, agent in _run_dirs(RUNS_SWEBENCH):
        for test_file in sorted(run_dir.glob("*_test.txt")):
            m = TEST_FILE_RE.match(test_file.name)
            if not m:
                continue
            instance_id = m.group("instance_id")
            arm = m.group("arm")
            run = int(m.group("run"))
            dataset = dataset_map.get(instance_id, "unknown")
            if dataset in EXCLUDED_DATASETS:
                continue
            jsonl = run_dir / f"{instance_id}_{arm}_run{run}.jsonl"
            yield _row_from_run(
                benchmark="swebench", dataset=dataset, instance_id=instance_id,
                seed=seed, agent=agent, arm=arm, run=run,
                verdict=_read_verdict(test_file),
                jsonl=jsonl, result_path=jsonl,
            )


def collect_artifact() -> Iterator[dict]:
    for run_dir, seed, agent in _run_dirs(RUNS_ARTIFACT):
        for instance_dir in sorted(run_dir.iterdir()):
            if not instance_dir.is_dir() or instance_dir.name.startswith("_"):
                continue
            instance_id = instance_dir.name
            for arm_dir in sorted(instance_dir.iterdir()):
                if not arm_dir.is_dir():
                    continue
                arm = arm_dir.name
                for run_subdir in sorted(arm_dir.iterdir()):
                    if not run_subdir.is_dir() or not run_subdir.name.startswith("run"):
                        continue
                    try:
                        run = int(run_subdir.name[3:])
                    except ValueError:
                        continue
                    result_path = run_subdir / "result.json"
                    if not result_path.is_file():
                        continue
                    try:
                        with result_path.open("r", encoding="utf-8") as f:
                            data = json.load(f)
                    except (OSError, json.JSONDecodeError):
                        continue
                    jsonl = run_subdir / "agent.jsonl"
                    row = _row_from_run(
                        benchmark="artifact",
                        dataset=_artifact_category(instance_id),
                        instance_id=instance_id, seed=seed, agent=agent,
                        arm=arm, run=run, verdict=data.get("verdict", "ERROR"),
                        jsonl=jsonl, result_path=result_path,
                        surface_default=data.get("agent_surface", "claude_code"),
                        agent_version_default=(data.get("agent_version") or data.get("claude_version")),
                    )
                    # ``result.json`` is the authoritative source for the artifact
                    # harness's externally-measured wall time and grader-reported
                    # cost/turns. Prefer it over the JSONL-derived values when present.
                    for key, src in (("cost_usd", "cost_usd"), ("num_turns", "num_turns"), ("wall_secs", "wall_secs")):
                        v = data.get(src)
                        if v is not None:
                            row[key] = v
                    yield row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "paper" / "data" / "all_results.csv"),
        help="Output CSV path (default: paper/data/all_results.csv)",
    )
    args = parser.parse_args()

    dataset_map = _swebench_dataset_map()
    rows = list(collect_swebench(dataset_map)) + list(collect_artifact())

    # Build the entire CSV in memory, then write it in one go. An earlier
    # incremental-writerow version produced sporadic 4-byte boundary corruption
    # on this filesystem; the in-memory build is bulletproof and the volume
    # (~3.5k rows) is tiny.
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(buf.getvalue(), encoding="utf-8")

    bench_counts: dict[str, int] = {}
    for r in rows:
        bench_counts[r["benchmark"]] = bench_counts.get(r["benchmark"], 0) + 1
    print(f"Wrote {len(rows)} rows to {out}")
    for bench, n in sorted(bench_counts.items()):
        print(f"  {bench}: {n}")


if __name__ == "__main__":
    main()
