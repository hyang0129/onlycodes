"""Per-run-instance result parser.

Single entry point: ``parse_run(jsonl_path)`` returns a ``RunResult`` for one
agent invocation. Used by ``scripts/collect_results.py`` to populate the cross-
seed CSV — no other consumer should reach into the raw JSONL files directly.

Surface dispatch is automatic, keyed off the ``meta`` line at the top of the
agent log:

  * **Claude** (``agent_surface == "claude_code"``) — parse the ``.jsonl`` only.
    Token counts, ``num_turns``, ``duration_ms`` and ``total_cost_usd`` all live
    on the final ``result`` line; tool invocations are ``tool_use`` blocks in
    ``assistant`` messages.

  * **Codex** (``agent_surface == "codex_cli"``) — parse the sibling
    ``.rollout.jsonl`` for the per-event LLM stream (timestamps, running token
    totals, individual ``function_call`` items). Cost is reconstructed from the
    final token totals × the codex price table (reusing
    ``swebench.runner.CodexRunner._load_codex_prices``). The codex ``.jsonl``
    itself only carries the wrapping ``turn.completed`` summary; the rollout is
    strictly more detailed, so prefer it. If the rollout is missing we fall
    back to ``CodexRunner().extract_metadata(jsonl)`` and report what we can.

Returns are best-effort: every field is ``Optional`` and missing data is
``None``, never zero. Callers must distinguish "agent did 0 of X" from "we
couldn't extract X".
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class RunResult:
    surface: str | None             # "claude_code" | "codex_cli" | None
    model: str | None
    agent_version: str | None

    cost_usd: float | None
    num_turns: int | None           # native agent loop count (claude: many; codex: 1)
    tool_calls: int | None          # total tool invocations (function_call equivalents)
    llm_calls: int | None           # number of model API calls

    input_tokens: int | None        # total prompt tokens INCLUDING cached
    cached_input_tokens: int | None
    output_tokens: int | None       # for codex, this already includes reasoning_tokens
    reasoning_tokens: int | None    # codex only; None for claude

    # First billed model call. Used by the cache-floor cost adjustment:
    # the median first_call_cache_read across same-(benchmark, seed, arm) tasks
    # represents the steady-state warm system-prompt cache; tasks below median
    # are bumped up to median to compensate for unlucky cold-start evictions.
    # Both fields are observed directly from per-call data, not estimated.
    first_call_input_tokens: int | None     # total prompt tokens of call 1 (input + cache_read + cache_creation)
    first_call_cache_read: int | None       # cache_read_input_tokens of call 1

    wall_secs: int | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------- shared helpers ----------------

def _iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                yield json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue


def _read_first_obj(path: Path) -> dict | None:
    for obj in _iter_jsonl(path):
        return obj if isinstance(obj, dict) else None
    return None


def _read_meta(path: Path) -> tuple[str | None, str | None, str | None]:
    """Return (surface, agent_version, model) from the first ``meta`` line, if any."""
    first = _read_first_obj(path)
    if isinstance(first, dict) and first.get("type") == "meta":
        return first.get("agent_surface"), first.get("agent_version"), first.get("model")
    return None, None, None


# ---------------- Claude ----------------

def _parse_claude(jsonl: Path, agent_version: str | None) -> RunResult:
    tool_calls = 0
    llm_calls = 0
    result_line: dict | None = None
    model: str | None = None
    # Dedupe assistant messages by message.id — Anthropic's streaming surface
    # emits the same id across multiple delta events with cumulative usage,
    # and we only want the first *unique* message for the first-call signal.
    seen_msg_ids: set[str] = set()
    first_call_usage: dict | None = None
    for obj in _iter_jsonl(jsonl):
        if not isinstance(obj, dict):
            continue
        t = obj.get("type")
        if t == "assistant":
            llm_calls += 1
            msg = obj.get("message") or {}
            msg_id = msg.get("id")
            if msg_id and msg_id in seen_msg_ids:
                continue
            seen_msg_ids.add(msg_id or f"_pos_{len(seen_msg_ids)}")
            if model is None:
                m = msg.get("model")
                if isinstance(m, str):
                    model = m
            if first_call_usage is None:
                u = msg.get("usage")
                if isinstance(u, dict):
                    first_call_usage = u
            for block in (msg.get("content") or []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_calls += 1
        elif t == "result":
            result_line = obj

    cost = num_turns = wall = None
    input_tok = cached_tok = output_tok = None
    if isinstance(result_line, dict):
        c = result_line.get("total_cost_usd")
        if isinstance(c, (int, float)):
            cost = float(c)
        nt = result_line.get("num_turns")
        if isinstance(nt, int):
            num_turns = nt
        d = result_line.get("duration_ms")
        if isinstance(d, (int, float)):
            wall = int(d / 1000)
        usage = result_line.get("usage")
        if isinstance(usage, dict):
            inp = int(usage.get("input_tokens") or 0)
            cr = int(usage.get("cache_read_input_tokens") or 0)
            cc = int(usage.get("cache_creation_input_tokens") or 0)
            input_tok = inp + cr + cc
            cached_tok = cr
            output_tok = int(usage.get("output_tokens") or 0)

    first_input = first_cache_read = None
    if isinstance(first_call_usage, dict):
        fi = int(first_call_usage.get("input_tokens") or 0)
        fcr = int(first_call_usage.get("cache_read_input_tokens") or 0)
        fcc = int(first_call_usage.get("cache_creation_input_tokens") or 0)
        first_input = fi + fcr + fcc
        first_cache_read = fcr

    return RunResult(
        surface="claude_code",
        model=model,
        agent_version=agent_version,
        cost_usd=cost,
        num_turns=num_turns,
        tool_calls=tool_calls,
        llm_calls=llm_calls or None,
        input_tokens=input_tok,
        cached_input_tokens=cached_tok,
        output_tokens=output_tok,
        reasoning_tokens=None,
        first_call_input_tokens=first_input,
        first_call_cache_read=first_cache_read,
        wall_secs=wall,
    )


# ---------------- Codex ----------------

# Rollout response_item payload types that represent a tool invocation. Codex
# exposes both the built-in shell (``function_call`` named ``exec_command``) and
# MCP tools (``function_call`` named ``execute_code`` etc.); ``custom_tool_call``
# is used by ``apply_patch`` and similar bespoke verbs. All three should be
# counted as one tool call apiece.
_CODEX_TOOL_PAYLOAD_TYPES = {"function_call", "custom_tool_call"}


# Claude pricing (USD per 1M tokens). Hardcoded because the harness has always
# taken ``total_cost_usd`` directly from Anthropic's result line and never needed
# a local rate table for the orig cost — only the cache-floor adjustment delta
# requires the rate gap (input − cache_read). Standard tier, claude-sonnet-4-6.
# Sources cross-checked 2026-05-26: https://docs.claude.com/en/docs/about-claude/pricing
CLAUDE_PRICES: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {
        "input": 3.00,
        "cache_creation_5m": 3.75,
        "cache_creation_1h": 6.00,
        "cache_read": 0.30,
        "output": 15.00,
    },
}
CLAUDE_DEFAULT_MODEL = "claude-sonnet-4-6"


def _codex_price_table():
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from swebench.runner import _load_codex_prices  # type: ignore
        return _load_codex_prices()
    except Exception:
        return {}


def _codex_cost(model: str | None, input_tok: int | None, cached_tok: int | None, output_tok: int | None) -> float | None:
    """Re-implement the codex cost formula on top of the rollout totals.

    Mirrors ``swebench.runner.CodexRunner.extract_metadata`` so the two paths
    can't drift: ``output_tokens`` already includes reasoning, and
    ``input_tokens`` already includes cached.
    """
    if model is None or input_tok is None or cached_tok is None or output_tok is None:
        return None
    prices = _codex_price_table().get(model)
    if prices is None:
        return None
    non_cached_input = max(0, input_tok - cached_tok)
    return (
        non_cached_input * prices["input"]
        + cached_tok * prices["cached_input"]
        + output_tok * prices["output"]
    ) / 1_000_000.0


def _parse_codex_rollout(rollout: Path) -> dict:
    """Return {tool_calls, llm_calls, wall_secs, input_tokens, cached_input_tokens,
    output_tokens, reasoning_tokens, first_call_input_tokens, first_call_cache_read}
    from a codex rollout.

    Any field whose source events were absent is omitted from the returned dict.
    """
    out: dict[str, Any] = {}
    tool_calls = 0
    llm_calls = 0
    first_ts = last_ts = None
    last_total_usage: dict | None = None
    first_call_usage: dict | None = None

    for obj in _iter_jsonl(rollout):
        if not isinstance(obj, dict):
            continue
        ts = obj.get("timestamp")
        if isinstance(ts, str):
            if first_ts is None:
                first_ts = ts
            last_ts = ts
        t = obj.get("type")
        payload = obj.get("payload") or {}
        pt = payload.get("type") if isinstance(payload, dict) else None
        if t == "response_item" and pt in _CODEX_TOOL_PAYLOAD_TYPES:
            tool_calls += 1
        elif t == "event_msg" and pt == "token_count":
            llm_calls += 1
            info = payload.get("info") if isinstance(payload, dict) else None
            if isinstance(info, dict):
                ttu = info.get("total_token_usage")
                if isinstance(ttu, dict):
                    last_total_usage = ttu
                # First per-call usage. Codex emits a call-0 handshake event
                # with last_token_usage=None; we skip those and grab the first
                # event where input_tokens > 0 — that's the first billed call.
                if first_call_usage is None:
                    ltu = info.get("last_token_usage")
                    if isinstance(ltu, dict) and int(ltu.get("input_tokens") or 0) > 0:
                        first_call_usage = ltu

    out["tool_calls"] = tool_calls
    out["llm_calls"] = llm_calls or None
    if first_ts and last_ts:
        try:
            t0 = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            out["wall_secs"] = int((t1 - t0).total_seconds())
        except ValueError:
            pass
    if last_total_usage is not None:
        # Codex rollout reports running cumulative totals — the LAST one is the
        # final total, no summing needed.
        out["input_tokens"] = int(last_total_usage.get("input_tokens") or 0)
        out["cached_input_tokens"] = int(last_total_usage.get("cached_input_tokens") or 0)
        out["output_tokens"] = int(last_total_usage.get("output_tokens") or 0)
        out["reasoning_tokens"] = int(last_total_usage.get("reasoning_output_tokens") or 0)
    if first_call_usage is not None:
        out["first_call_input_tokens"] = int(first_call_usage.get("input_tokens") or 0)
        out["first_call_cache_read"] = int(first_call_usage.get("cached_input_tokens") or 0)
    return out


def _parse_codex_jsonl_fallback(jsonl: Path) -> dict:
    """Last-resort extraction from the codex ``.jsonl`` when rollout is absent.

    Only used when ``<jsonl>.rollout.jsonl`` doesn't exist. Counts tool items
    and sums ``turn.completed.usage`` blocks (which is what the old code did).
    Wall time isn't available from this file.
    """
    out: dict[str, Any] = {}
    tool_calls = 0
    turns_seen = 0
    totals = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0}
    saw_usage = False
    for obj in _iter_jsonl(jsonl):
        if not isinstance(obj, dict):
            continue
        t = obj.get("type")
        if t == "item.completed":
            item = obj.get("item") or {}
            if isinstance(item, dict) and item.get("type") in ("command_execution", "mcp_tool_call"):
                tool_calls += 1
        elif t == "turn.completed":
            turns_seen += 1
            u = obj.get("usage")
            if isinstance(u, dict) and any(k in u for k in ("input_tokens", "output_tokens", "cached_input_tokens")):
                saw_usage = True
                totals["input_tokens"] += int(u.get("input_tokens") or 0)
                totals["cached_input_tokens"] += int(u.get("cached_input_tokens") or 0)
                totals["output_tokens"] += int(u.get("output_tokens") or 0)
                totals["reasoning_tokens"] += int(u.get("reasoning_output_tokens") or 0)
    out["tool_calls"] = tool_calls
    out["llm_calls"] = turns_seen or None
    if saw_usage:
        out.update(totals)
    return out


def _parse_codex(jsonl: Path, agent_version: str | None, model: str | None) -> RunResult:
    rollout = jsonl.with_suffix(jsonl.suffix + ".rollout.jsonl")
    extracted = _parse_codex_rollout(rollout) if rollout.is_file() else _parse_codex_jsonl_fallback(jsonl)

    # Codex's native "num_turns" is always 1 (one wrapping agent turn containing
    # many tool calls). We preserve that for parity with the CSV's existing
    # column semantics, but llm_calls is the meaningful cross-agent analogue.
    num_turns = None
    for obj in _iter_jsonl(jsonl):
        if isinstance(obj, dict) and obj.get("type") == "turn.started":
            num_turns = (num_turns or 0) + 1

    input_tok = extracted.get("input_tokens")
    cached_tok = extracted.get("cached_input_tokens")
    output_tok = extracted.get("output_tokens")
    reasoning_tok = extracted.get("reasoning_tokens")
    cost = _codex_cost(model, input_tok, cached_tok, output_tok)

    return RunResult(
        surface="codex_cli",
        model=model,
        agent_version=agent_version,
        cost_usd=cost,
        num_turns=num_turns,
        tool_calls=extracted.get("tool_calls"),
        llm_calls=extracted.get("llm_calls"),
        input_tokens=input_tok,
        cached_input_tokens=cached_tok,
        output_tokens=output_tok,
        reasoning_tokens=reasoning_tok,
        first_call_input_tokens=extracted.get("first_call_input_tokens"),
        first_call_cache_read=extracted.get("first_call_cache_read"),
        wall_secs=extracted.get("wall_secs"),
    )


# ---------------- entry point ----------------

def parse_run(jsonl: Path) -> RunResult:
    """Parse a single agent run log into a RunResult.

    ``jsonl`` is the main agent log: ``<run>.jsonl`` for SWE-bench, or
    ``agent.jsonl`` for an artifact run. The codex parser will auto-locate the
    ``.rollout.jsonl`` sibling.
    """
    surface, version, model = _read_meta(jsonl)
    if surface == "codex_cli":
        return _parse_codex(jsonl, version, model)
    # Default to the claude parser. The Claude harness historically wrote a
    # meta line with surface="claude_code"; runs predating that field also fall
    # through here (the claude parser is tolerant of missing meta).
    return _parse_claude(jsonl, version)


if __name__ == "__main__":
    # Smoke test: pass a path on the command line.
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("jsonl", type=Path)
    args = parser.parse_args()
    print(json.dumps(parse_run(args.jsonl).as_dict(), indent=2))
