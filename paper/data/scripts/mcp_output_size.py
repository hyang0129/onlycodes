#!/usr/bin/env python3
"""
mcp_output_size.py — per-call tool-output distribution per (agent, benchmark, arm).

Backs `\\result{mcp_output_size}{...}` macros referenced by paper/06_discussion.md §6.2.

Walks all Codex rollouts and Claude logs across seeds 1/2/3 for both SWE-bench and
Artifact, extracts per-tool-call output sizes (and per-tool-call args + per-run agent
prose), and emits a single wide-format CSV with one row per (cell, arm) and one column
per metric. The §6.2 macros key off this CSV via `<cell>:<arm>:<metric>` lookups.

Mirrors the inline analysis run during paper/q2_token_gap_investigation.md
(sections 2, 3, 4, 5, 8.1).

Two known divergences from paper/data/raw/all_results.csv aggregates:
  - Codex `tools_per_llm` is ~7% lower here (e.g. 1.26 vs 1.35 for codex_swebench:baseline)
    because this script walks every rollout in runs/swebench/full_run_seed_*_codex_v2/
    (~330/arm pooled across seeds), while all_results.csv aggregates the subset of
    runs that propagate to the headline pipeline (~300/arm).
  - Claude `tools_per_llm` is ~2× higher here than the headline (e.g. 0.65 vs 0.34
    for claude_swebench:baseline) because the canonical parser at
    scripts/parse_run.py:102-128 dedupes assistant messages by message.id and
    processes only the first record per id — but Anthropic's streaming surface
    emits `tool_use` blocks across LATER delta records, so the canonical parser
    undercounts. The count emitted here matches the paired `tool_result` count
    in user messages (each tool_use → one tool_result), which is the truthful
    one. §6.2 prose should cite this CSV for `tools_per_llm`, not all_results.csv.

CSV consumers:
  - paper/06_discussion.md §6.2 macros: codex_swebench:{baseline,onlycode}:{tools_per_llm,median_chars,p99_chars}
                                        claude_swebench:{baseline,onlycode}:p99_chars
  - paper/q2_token_gap_investigation.md tables in §2, §3, §4, §5, §6

Run:
  python3 paper/data/scripts/mcp_output_size.py
"""
from __future__ import annotations

import csv
import glob
import json
import os
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_CSV = REPO_ROOT / "paper" / "data" / "mcp_output_size.csv"

# Arm name → "rival" or "code_arm" role per benchmark, used downstream by macros.
SWEBENCH_ARMS = ("baseline", "bash_only", "onlycode")
ARTIFACT_ARMS = ("tool_rich", "bash_only", "code_only")


# --------------------------------------------------------------------------- #
# Walkers — one per log format.
# --------------------------------------------------------------------------- #

def walk_codex_rollout(rollout_path: Path) -> tuple[list[int], list[int], int, int]:
    """Return (out_sizes, args_sizes, agent_msg_chars, n_llm_calls).

    Codex rollouts log `response_item` records with payload.type in:
      - "function_call":         args is a JSON string in payload.arguments
      - "function_call_output":  output is a string in payload.output
      - "message":               content is list of {"type":"output_text","text":...}
    LLM-call count is the number of `event_msg.token_count` records with non-null info.
    """
    outs: list[int] = []
    args: list[int] = []
    msg_chars = 0
    llm_calls = 0
    with rollout_path.open() as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = d.get("type")
            payload = d.get("payload") or {}
            pt = payload.get("type") if isinstance(payload, dict) else None
            if t == "response_item":
                if pt == "function_call_output":
                    o = payload.get("output")
                    if isinstance(o, str):
                        outs.append(len(o))
                elif pt == "function_call":
                    a = payload.get("arguments")
                    if isinstance(a, str):
                        args.append(len(a))
                elif pt == "message":
                    content = payload.get("content")
                    if isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict):
                                txt = c.get("text", "")
                                if isinstance(txt, str):
                                    msg_chars += len(txt)
            elif t == "event_msg" and pt == "token_count":
                info = payload.get("info")
                if isinstance(info, dict):
                    ltu = info.get("last_token_usage")
                    if isinstance(ltu, dict) and int(ltu.get("input_tokens") or 0) > 0:
                        llm_calls += 1
    return outs, args, msg_chars, llm_calls


def walk_claude_log(log_path: Path) -> tuple[list[int], list[int], int, int]:
    """Return (out_sizes, args_sizes, agent_msg_chars, n_llm_calls).

    Claude `.jsonl` (or `agent.jsonl`) records:
      - type == "assistant":   message.content has tool_use items (input is dict → JSON arg size)
                                                 and text items (text → agent prose)
      - type == "user":        message.content has tool_result items (content is str OR list of text blocks)
    LLM-call count = number of assistant records (one assistant response per LLM call).
    """
    outs: list[int] = []
    args: list[int] = []
    msg_chars = 0
    llm_calls = 0
    with log_path.open() as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = d.get("type")
            msg = d.get("message", {}) if isinstance(d.get("message"), dict) else {}
            content = msg.get("content", [])
            if t == "assistant":
                llm_calls += 1
                if isinstance(content, list):
                    for c in content:
                        if not isinstance(c, dict):
                            continue
                        ct = c.get("type")
                        if ct == "tool_use":
                            args.append(len(json.dumps(c.get("input", {}))))
                        elif ct == "text":
                            txt = c.get("text", "")
                            if isinstance(txt, str):
                                msg_chars += len(txt)
            elif t == "user":
                if isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "tool_result":
                            tc = c.get("content", "")
                            if isinstance(tc, str):
                                outs.append(len(tc))
                            elif isinstance(tc, list):
                                outs.append(
                                    sum(
                                        len(x.get("text", ""))
                                        for x in tc
                                        if isinstance(x, dict) and isinstance(x.get("text"), str)
                                    )
                                )
    return outs, args, msg_chars, llm_calls


# --------------------------------------------------------------------------- #
# Run discovery — one entry per (cell, arm).
# --------------------------------------------------------------------------- #

def _arm_of_swebench_filename(p: Path) -> str | None:
    name = p.name
    for arm in SWEBENCH_ARMS:
        if f"_{arm}_run" in name:
            return arm
    return None


def _is_codex_artifact_run(agent_jsonl: Path) -> bool:
    """Check the meta line of a Claude/Codex artifact agent.jsonl to see which agent ran."""
    try:
        with agent_jsonl.open() as f:
            first = f.readline()
        return "codex" in first.lower()
    except OSError:
        return False


def discover_runs():
    """Yield (cell, arm, walker, log_path) tuples."""
    swe_root = REPO_ROOT / "runs" / "swebench"
    art_root = REPO_ROOT / "runs" / "artifact"

    # ---- Codex SWE-bench: rollout files in *_codex_v2 dirs ----
    for seed_dir in sorted(swe_root.glob("full_run_seed_*_codex_v2")):
        for rollout in seed_dir.glob("*.rollout.jsonl"):
            arm = _arm_of_swebench_filename(Path(rollout.name.replace(".rollout.jsonl", "")))
            if arm:
                yield "codex_swebench", arm, walk_codex_rollout, rollout

    # ---- Claude SWE-bench: .jsonl in non-codex_v2 seed dirs ----
    for seed_dir in sorted(swe_root.glob("full_run_seed_*")):
        if seed_dir.name.endswith("_codex_v2"):
            continue
        for jsonl in seed_dir.glob("*_run*.jsonl"):
            if jsonl.name.endswith(".rollout.jsonl") or jsonl.name.endswith("_test.txt"):
                continue
            arm = _arm_of_swebench_filename(jsonl)
            if arm:
                yield "claude_swebench", arm, walk_claude_log, jsonl

    # ---- Artifact (both agents): agent.jsonl per task/arm/run, agent inferred from meta line ----
    for seed_dir in sorted(art_root.glob("full_run_seed_*")):
        if "_codex_v2" in seed_dir.name:
            agent_kind = "codex"  # the v2 dir is codex-only
        else:
            agent_kind = None  # decide per-file from meta
        for arm in ARTIFACT_ARMS:
            for agent_jsonl in seed_dir.glob(f"*/{arm}/run*/agent.jsonl"):
                kind = agent_kind or ("codex" if _is_codex_artifact_run(agent_jsonl) else "claude")
                if kind == "codex":
                    rollout = agent_jsonl.with_suffix(agent_jsonl.suffix + ".rollout.jsonl")
                    if rollout.is_file():
                        yield "codex_artifact", arm, walk_codex_rollout, rollout
                else:
                    yield "claude_artifact", arm, walk_claude_log, agent_jsonl


# --------------------------------------------------------------------------- #
# Aggregation.
# --------------------------------------------------------------------------- #

def percentile(xs_sorted: list[int], p: float) -> int:
    if not xs_sorted:
        return 0
    idx = max(0, min(len(xs_sorted) - 1, int(p * len(xs_sorted))))
    return xs_sorted[idx]


def aggregate():
    """Returns dict keyed by (cell, arm) with metric dict values."""
    pooled_outs: dict[tuple[str, str], list[int]] = defaultdict(list)
    per_run_calls: dict[tuple[str, str], list[int]] = defaultdict(list)
    per_run_args: dict[tuple[str, str], list[float]] = defaultdict(list)
    per_run_msg: dict[tuple[str, str], list[int]] = defaultdict(list)
    per_run_llm: dict[tuple[str, str], list[int]] = defaultdict(list)

    n_files = 0
    for cell, arm, walker, path in discover_runs():
        outs, args, msg_chars, llm_calls = walker(path)
        if not outs and not llm_calls:
            continue  # empty/corrupt log
        key = (cell, arm)
        pooled_outs[key].extend(outs)
        per_run_calls[key].append(len(outs))
        per_run_args[key].append(statistics.mean(args) if args else 0.0)
        per_run_msg[key].append(msg_chars)
        per_run_llm[key].append(llm_calls)
        n_files += 1

    sys.stderr.write(f"[mcp_output_size] processed {n_files} log files\n")

    results = {}
    for key, outs in pooled_outs.items():
        s = sorted(outs)
        calls_run = per_run_calls[key]
        llm_run = per_run_llm[key]
        mean_calls = statistics.mean(calls_run) if calls_run else 0.0
        mean_llm = statistics.mean(llm_run) if llm_run else 0.0
        results[key] = {
            "n_runs": len(calls_run),
            "n_calls": len(s),
            "tools_per_llm": (mean_calls / mean_llm) if mean_llm else 0.0,
            "mean_chars": statistics.mean(s) if s else 0.0,
            "median_chars": percentile(s, 0.50),
            "p75_chars": percentile(s, 0.75),
            "p90_chars": percentile(s, 0.90),
            "p95_chars": percentile(s, 0.95),
            "p99_chars": percentile(s, 0.99),
            "max_chars": s[-1] if s else 0,
            "calls_per_run": mean_calls,
            "args_per_call": statistics.mean(per_run_args[key]) if per_run_args[key] else 0.0,
            "agent_msg_chars_per_run": statistics.mean(per_run_msg[key]) if per_run_msg[key] else 0.0,
            "llm_calls_per_run": mean_llm,
        }
    return results


# --------------------------------------------------------------------------- #
# CSV emission.
# --------------------------------------------------------------------------- #

CELL_ORDER = ("codex_swebench", "codex_artifact", "claude_swebench", "claude_artifact")
ARM_ORDER = {
    "codex_swebench": SWEBENCH_ARMS,
    "claude_swebench": SWEBENCH_ARMS,
    "codex_artifact": ARTIFACT_ARMS,
    "claude_artifact": ARTIFACT_ARMS,
}
METRIC_COLS = (
    "n_runs", "n_calls", "tools_per_llm",
    "mean_chars", "median_chars", "p75_chars", "p90_chars", "p95_chars", "p99_chars", "max_chars",
    "calls_per_run", "args_per_call", "agent_msg_chars_per_run", "llm_calls_per_run",
)


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], text=True
        ).strip()
    except subprocess.CalledProcessError:
        return "unknown"


def _fmt(v, col):
    if col in ("n_runs", "n_calls", "median_chars", "p75_chars", "p90_chars", "p95_chars", "p99_chars", "max_chars"):
        return str(int(round(v)))
    if col == "tools_per_llm":
        return f"{v:.3f}"
    return f"{v:.1f}"


def emit_csv(results: dict[tuple[str, str], dict]) -> None:
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    header_comments = [
        f"# source_commit: {_git_head()}",
        f"# generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "# generator: paper/data/scripts/mcp_output_size.py",
        "# key_schema: cell:arm",
        "# default_precision: 2",
        "#",
        "# Per-tool-call output distribution by (agent × benchmark × arm).",
        "# Pooled across seeds 1/2/3. Mirrors inline analysis in",
        "# paper/q2_token_gap_investigation.md sections 2/3/4/5/8.1.",
        "#",
        "# Cells become \\result{mcp_output_size}{<cell>:<arm>:<metric>}.",
        "# Example: \\result{mcp_output_size}{codex_swebench:onlycode:p99_chars}",
        "#",
        "# Char counts are raw len() of tool_result content or function_call_output payload",
        "# strings (no tokenization). Cross-arm comparisons within a cell are valid; cross-cell",
        "# absolute comparisons are biased by JSON-envelope vs verbatim-stdout serialization.",
    ]
    with OUT_CSV.open("w") as f:
        for line in header_comments:
            f.write(line + "\n")
        writer = csv.writer(f)
        writer.writerow(("cell", "arm", *METRIC_COLS))
        for cell in CELL_ORDER:
            for arm in ARM_ORDER[cell]:
                row = results.get((cell, arm))
                if row is None:
                    writer.writerow((cell, arm, *([""] * len(METRIC_COLS))))
                    continue
                writer.writerow((cell, arm, *(_fmt(row[c], c) for c in METRIC_COLS)))
    sys.stderr.write(f"[mcp_output_size] wrote {OUT_CSV}\n")


def main():
    results = aggregate()
    emit_csv(results)
    # Echo the §6.2 macro-targeted values for quick visual verification.
    print("\n--- §6.2 macro values ---")
    for key in [
        ("codex_swebench", "baseline"),
        ("codex_swebench", "onlycode"),
        ("claude_swebench", "baseline"),
        ("claude_swebench", "onlycode"),
    ]:
        r = results.get(key)
        if r is None:
            print(f"{key}: missing")
            continue
        print(
            f"{key[0]}:{key[1]}: "
            f"tools_per_llm={r['tools_per_llm']:.3f}  "
            f"median={r['median_chars']}  "
            f"p99={r['p99_chars']}  "
            f"max={r['max_chars']}"
        )


if __name__ == "__main__":
    main()
