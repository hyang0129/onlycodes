"""Collect SWE-bench and artifact results across all seed runs into a single CSV.

Walks every ``runs/swebench/full_run_seed_<N>[_codex_v2]/`` and
``runs/artifact/full_run_seed_<N>[_codex_v2]/`` directory, emits one row per
(instance_id, seed, agent, arm, run). Intended as the paper's source of truth
for cross-seed stats.

Usage:
    python scripts/collect_results.py [--out paper/data/all_results.csv]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Iterator

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
    "benchmark",       # swebench | artifact
    "dataset",         # swebench-verified-mini | swebench-datasci-mini | adhoc | <artifact-category>
    "instance_id",
    "seed",
    "agent",           # claude | codex
    "arm",
    "run",
    "verdict",         # PASS | FAIL | env_fail | ERROR
    "cost_usd",
    "num_turns",
    "wall_secs",
    "agent_surface",   # claude_code | codex_cli (from meta/result file; source of truth)
    "agent_version",
    "result_path",     # JSONL (swebench) or result.json (artifact)
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


def _read_first_line_json(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            line = f.readline().strip()
        return json.loads(line) if line else None
    except (OSError, json.JSONDecodeError):
        return None


def _read_last_line_json(path: Path) -> dict | None:
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return None
            # Read tail bytes; result line is the last non-empty line.
            chunk = 8192
            f.seek(max(0, size - chunk))
            data = f.read().decode("utf-8", errors="replace")
        for line in reversed(data.splitlines()):
            line = line.strip()
            if line:
                return json.loads(line)
    except (OSError, json.JSONDecodeError):
        return None
    return None


def _extract_swebench_stats(jsonl: Path) -> tuple[float | None, int | None, int | None, str, str | None]:
    """Return (cost_usd, num_turns, wall_secs, agent_surface, agent_version)."""
    cost: float | None = None
    turns: int | None = None
    wall: int | None = None
    surface = "claude_code"
    version: str | None = None

    meta = _read_first_line_json(jsonl)
    if isinstance(meta, dict) and meta.get("type") == "meta":
        s = meta.get("agent_surface")
        if isinstance(s, str):
            surface = s
        v = meta.get("agent_version")
        if isinstance(v, str):
            version = v

    if surface == "codex_cli":
        # Re-use the runner's authoritative cost extractor for codex (price-table
        # lookup keyed by the model in the meta line). Wall time isn't recorded
        # in the codex result line, so it stays None.
        try:
            sys.path.insert(0, str(REPO_ROOT))
            from swebench.runner import CodexRunner
            cost, turns = CodexRunner().extract_metadata(jsonl)
        except Exception:
            pass
    else:
        result = _read_last_line_json(jsonl)
        if isinstance(result, dict) and result.get("type") == "result":
            c = result.get("total_cost_usd")
            if isinstance(c, (int, float)):
                cost = float(c)
            t = result.get("num_turns")
            if isinstance(t, int):
                turns = t
            d = result.get("duration_ms")
            if isinstance(d, (int, float)):
                wall = int(d / 1000)

    return cost, turns, wall, surface, version


def _read_verdict(test_path: Path) -> str:
    try:
        lines = test_path.read_text().strip().splitlines()
    except OSError:
        return "ERROR"
    if not lines:
        return "ERROR"
    last = lines[-1].strip()
    return last if last in ("PASS", "FAIL", "env_fail") else "ERROR"


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
            cost, turns, wall, surface, version = (
                _extract_swebench_stats(jsonl) if jsonl.exists() else (None, None, None, "claude_code", None)
            )
            yield {
                "benchmark": "swebench",
                "dataset": dataset,
                "instance_id": instance_id,
                "seed": seed,
                "agent": agent,
                "arm": arm,
                "run": run,
                "verdict": _read_verdict(test_file),
                "cost_usd": cost,
                "num_turns": turns,
                "wall_secs": wall,
                "agent_surface": surface,
                "agent_version": version,
                "result_path": str(jsonl.relative_to(REPO_ROOT)),
            }


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
                    yield {
                        "benchmark": "artifact",
                        "dataset": _artifact_category(instance_id),
                        "instance_id": instance_id,
                        "seed": seed,
                        "agent": agent,
                        "arm": arm,
                        "run": run,
                        "verdict": data.get("verdict", "ERROR"),
                        "cost_usd": data.get("cost_usd"),
                        "num_turns": data.get("num_turns"),
                        "wall_secs": data.get("wall_secs"),
                        "agent_surface": data.get("agent_surface", "claude_code"),
                        "agent_version": data.get("agent_version") or data.get("claude_version"),
                        "result_path": str(result_path.relative_to(REPO_ROOT)),
                    }


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

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    bench_counts: dict[str, int] = {}
    for r in rows:
        bench_counts[r["benchmark"]] = bench_counts.get(r["benchmark"], 0) + 1
    print(f"Wrote {len(rows)} rows to {out}")
    for bench, n in sorted(bench_counts.items()):
        print(f"  {bench}: {n}")


if __name__ == "__main__":
    main()
