"""Run-health audit for SWE-bench agent transcripts (#305, WS-G).

The spine (#299) is ~8,900 agent runs across two subscription-billed agents over
multiple days. The failure mode that silently corrupts the dataset is a run that
was **rate-limited / API-errored / wall-timed-out / never connected its MCP**:
the harness writes a transcript + a ``FAIL`` verdict, ``--resume`` then treats
the triple as *done*, and the bad run lands in the pass-rate and cost numbers as
if it were a genuine task failure.

Rather than wrap ``runner.invoke()`` with in-line retry, we **audit the JSONL**
(the source of truth) after the fact and classify each run. A run flagged as an
*infra* failure can be quarantined so a subsequent ``swebench run --resume`` pass
re-runs only those triples (resume is robust to missing files — see
``run._is_triple_complete``). This catches a broader class of problems than a
429-only retry and works post-hoc over run dirs that already exist.

Detection is **structural**, not text-matching: a *healthy* Claude transcript
literally contains the word "rate" (an informational ``rate_limit_event`` with
``status == "allowed"``), so we key off the typed fields, never a substring scan
of the whole file.

Surface-specific signatures
---------------------------
**claude_code** — terminal ``result`` line:
  * ``is_error == true`` or non-null ``api_error_status``      → ``api_error``
  * ``subtype == "error_max_turns"``                            → ``max_turns`` (soft)
  * ``subtype`` not ``success``/``error_max_turns``             → ``api_error``
  * any ``rate_limit_event`` with ``rate_limit_info.status``
    other than ``"allowed"``                                    → ``rate_limited``
  * a ``system``/``subtype == "wall_timeout"`` line             → ``wall_timeout``
  * no ``result`` line at all                                   → ``no_result``

**codex_cli** — native event stream (no ``result`` line):
  * no ``turn.completed`` event                                 → ``no_result``
  * an event whose type/status names an error, or a usage-limit
    message in an ``error``/``stream_error`` event              → ``api_error`` / ``rate_limited``

**both** — for arms that require the codebox MCP (``onlycode``/``code_only``):
  * zero ``mcp__codebox__`` / ``server:codebox`` tool uses      → ``mcp_failed``

``OK`` otherwise. ``max_turns`` is *soft* (a legitimate "agent gave up" outcome,
not infra) and is reported but not quarantined unless explicitly requested.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Status taxonomy
# ---------------------------------------------------------------------------

OK = "ok"
RATE_LIMITED = "rate_limited"
API_ERROR = "api_error"
WALL_TIMEOUT = "wall_timeout"
MAX_TURNS = "max_turns"
NO_RESULT = "no_result"
MCP_FAILED = "mcp_failed"
EMPTY = "empty"
UNREADABLE = "unreadable"

#: Infra/transient failures that corrupt the dataset → re-run on the next
#: ``--resume`` pass. ``MAX_TURNS`` is deliberately excluded (it is a genuine
#: capability outcome, not an environment failure).
HARD_STATUSES = frozenset(
    {RATE_LIMITED, API_ERROR, WALL_TIMEOUT, NO_RESULT, MCP_FAILED, EMPTY, UNREADABLE}
)
#: Reported but not auto-quarantined unless ``--include-soft``.
SOFT_STATUSES = frozenset({MAX_TURNS})

#: Severity order — when several signatures fire, the most actionable wins.
_SEVERITY = [
    RATE_LIMITED,
    API_ERROR,
    WALL_TIMEOUT,
    MCP_FAILED,
    NO_RESULT,
    MAX_TURNS,
    EMPTY,
    UNREADABLE,
    OK,
]

#: Arms whose run is meaningless without the codebox execute_code tool.
_MCP_REQUIRED_ARMS = {"code_only", "onlycode"}

#: Codex usage/rate-limit phrases (matched only inside typed error events, never
#: across the whole transcript — see module docstring).
_RATE_LIMIT_RE = re.compile(
    r"rate.?limit|429|too\s*many\s*requests|usage\s*limit|quota|overloaded",
    re.IGNORECASE,
)

# Filename: <instance_id>_<arm>_run<N>.jsonl
_STEM_RE = re.compile(r"^(.+)_(baseline|onlycode|bash_only|code_only|tool_rich)_run(\d+)$")


@dataclass
class RunAudit:
    """Classification of one agent transcript."""

    path: Path
    instance_id: str | None
    arm: str | None
    run: int | None
    surface: str | None
    status: str
    reasons: list[str] = field(default_factory=list)
    verdict: str | None = None
    cost_usd: float | None = None
    num_turns: int | None = None

    @property
    def needs_rerun(self) -> bool:
        return self.status in HARD_STATUSES

    @property
    def is_soft(self) -> bool:
        return self.status in SOFT_STATUSES

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "instance_id": self.instance_id,
            "arm": self.arm,
            "run": self.run,
            "surface": self.surface,
            "status": self.status,
            "reasons": self.reasons,
            "verdict": self.verdict,
            "cost_usd": self.cost_usd,
            "num_turns": self.num_turns,
            "needs_rerun": self.needs_rerun,
        }


# ---------------------------------------------------------------------------
# JSONL loading
# ---------------------------------------------------------------------------


def _load_lines(path: Path) -> tuple[list[dict], str]:
    """Return ``(parsed_json_objects, raw_text)``. Non-JSON lines are skipped in
    the object list but kept in ``raw_text`` (the codex banner
    ``"Reading additional input from stdin..."`` is an expected non-JSON line)."""
    raw = path.read_text()
    objs: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            objs.append(obj)
    return objs, raw


def _meta(objs: list[dict]) -> dict:
    for o in objs:
        if o.get("type") == "meta":
            return o
    return {}


def _pick_status(candidates: list[str]) -> str:
    """Most-severe status among the fired signatures (``OK`` if none)."""
    for s in _SEVERITY:
        if s in candidates:
            return s
    return OK


# ---------------------------------------------------------------------------
# Surface classifiers
# ---------------------------------------------------------------------------


def _codebox_used(raw: str) -> bool:
    # Mirror container_agent._codebox_was_used: Claude names the tool
    # ``mcp__codebox__*``; Codex emits ``"server":"codebox"``.
    return (
        "mcp__codebox__" in raw
        or '"server":"codebox"' in raw
        or '"server": "codebox"' in raw
    )


def _classify_claude(objs: list[dict], raw: str, arm: str | None) -> tuple[str, list[str]]:
    fired: list[str] = []
    reasons: list[str] = []

    # Rate-limit events: the request was served unless the status says otherwise.
    # ``allowed`` and ``allowed_warning`` (allowed, but near the cap) both mean the
    # call went through — only a non-``allowed*`` status (e.g. "rejected",
    # "blocked", "exceeded") indicates the turn was actually throttled.
    def _is_served(val: object) -> bool:
        return val is None or str(val).startswith("allowed") or val == "disabled"

    for o in objs:
        if o.get("type") == "rate_limit_event":
            info = o.get("rate_limit_info") or {}
            status = info.get("status")
            if not _is_served(status):
                fired.append(RATE_LIMITED)
                reasons.append(f"rate_limit_event.status={status!r}")
            over = info.get("overageStatus")
            if not _is_served(over):
                fired.append(RATE_LIMITED)
                reasons.append(f"rate_limit_event.overageStatus={over!r}")

    # Wall-time kill (runner writes a system/wall_timeout line).
    for o in objs:
        if o.get("type") == "system" and o.get("subtype") == "wall_timeout":
            fired.append(WALL_TIMEOUT)
            reasons.append(f"wall_timeout after {o.get('wall_seconds')}s")

    # Terminal result line.
    result = next((o for o in objs if o.get("type") == "result"), None)
    if result is None:
        fired.append(NO_RESULT)
        reasons.append("no result line (agent did not finish)")
    else:
        api_err = result.get("api_error_status")
        subtype = result.get("subtype")
        if result.get("is_error") is True:
            fired.append(API_ERROR)
            reasons.append(f"result.is_error=true (subtype={subtype!r})")
        if api_err:  # non-null, non-empty
            status = RATE_LIMITED if _RATE_LIMIT_RE.search(str(api_err)) else API_ERROR
            fired.append(status)
            reasons.append(f"result.api_error_status={api_err!r}")
        if subtype == "error_max_turns":
            fired.append(MAX_TURNS)
            reasons.append("result.subtype=error_max_turns")
        elif subtype not in (None, "success"):
            fired.append(API_ERROR)
            reasons.append(f"result.subtype={subtype!r}")

    if arm in _MCP_REQUIRED_ARMS and not _codebox_used(raw):
        fired.append(MCP_FAILED)
        reasons.append("zero mcp__codebox__ tool uses (MCP never connected)")

    return _pick_status(fired), reasons


def _classify_codex(objs: list[dict], raw: str, arm: str | None) -> tuple[str, list[str]]:
    fired: list[str] = []
    reasons: list[str] = []

    # Typed error events (codex emits errors as their own event types/items).
    for o in objs:
        t = str(o.get("type", ""))
        blob = json.dumps(o)
        is_error_event = (
            "error" in t
            or o.get("status") in ("failed", "error")
            or (o.get("type") == "item.completed"
                and isinstance(o.get("item"), dict)
                and o["item"].get("type", "").endswith("error"))
        )
        if is_error_event:
            if _RATE_LIMIT_RE.search(blob):
                fired.append(RATE_LIMITED)
                reasons.append(f"error event ({t}) with usage/rate-limit text")
            else:
                fired.append(API_ERROR)
                reasons.append(f"error event ({t})")

    # A completed codex turn carries the usage block; none means the run died.
    if not any(o.get("type") == "turn.completed" for o in objs):
        fired.append(NO_RESULT)
        reasons.append("no turn.completed event (run did not produce a turn)")

    if arm in _MCP_REQUIRED_ARMS and not _codebox_used(raw):
        fired.append(MCP_FAILED)
        reasons.append("zero codebox tool uses (MCP never connected)")

    return _pick_status(fired), reasons


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _parse_stem(path: Path) -> tuple[str | None, str | None, int | None]:
    m = _STEM_RE.match(path.stem)
    if not m:
        return None, None, None
    return m.group(1), m.group(2), int(m.group(3))


def _verdict_from_test_txt(jsonl_path: Path) -> str | None:
    """Last non-empty line of the sibling ``_test.txt`` (the graded verdict)."""
    txt = jsonl_path.with_name(jsonl_path.stem + "_test.txt")
    if not txt.is_file():
        return None
    for line in reversed(txt.read_text().splitlines()):
        line = line.strip()
        if line:
            return line
    return None


def classify_run(jsonl_path: Path) -> RunAudit:
    """Classify a single agent transcript JSONL into a :class:`RunAudit`.

    Surface is read from the transcript's ``meta`` line; if absent it is inferred
    from line shapes (a ``result`` line ⇒ claude, ``turn.completed`` ⇒ codex).
    """
    jsonl_path = Path(jsonl_path)
    iid, arm, run = _parse_stem(jsonl_path)

    try:
        objs, raw = _load_lines(jsonl_path)
    except OSError as e:
        return RunAudit(jsonl_path, iid, arm, run, None, UNREADABLE, [f"unreadable: {e}"])

    if not objs and not raw.strip():
        return RunAudit(jsonl_path, iid, arm, run, None, EMPTY, ["empty transcript"])

    meta = _meta(objs)
    surface = meta.get("agent_surface")
    arm = meta.get("arm", arm)
    if iid is None:
        iid = meta.get("instance_id")
    if run is None and meta.get("run") is not None:
        run = meta.get("run")

    if surface is None:
        # Infer: a result line is Claude-only; turn.completed is Codex-only.
        if any(o.get("type") == "result" for o in objs):
            surface = "claude_code"
        elif any(o.get("type") == "turn.completed" for o in objs):
            surface = "codex_cli"

    if surface == "codex_cli":
        status, reasons = _classify_codex(objs, raw, arm)
    else:
        # Default to the claude classifier (also handles the older overlay format).
        status, reasons = _classify_claude(objs, raw, arm)

    # Best-effort metrics for the report (verdict / cost / turns).
    verdict = _verdict_from_test_txt(jsonl_path)
    if verdict is None:
        v = next((o for o in objs if o.get("type") == "verdict"), None)
        if v:
            verdict = v.get("verdict")
    cost = meta.get("total_cost_usd")
    turns = meta.get("num_turns")
    if cost is None:
        r = next((o for o in objs if o.get("type") == "result"), None)
        if r:
            cost = r.get("total_cost_usd")
            turns = r.get("num_turns")

    return RunAudit(
        path=jsonl_path,
        instance_id=iid,
        arm=arm,
        run=run,
        surface=surface,
        status=status,
        reasons=reasons,
        verdict=verdict,
        cost_usd=cost,
        num_turns=turns,
    )


def is_account_limited(jsonl_path: Path) -> bool:
    """True if a transcript shows an **account rate-limit / quota rejection** — an
    HTTP 429, a ``rate_limit_event`` whose status is not ``allowed*``, or a
    usage-limit error event (codex). This is the signal to *back off and pause*
    the run, distinct from a task FAIL or a one-off non-quota ``api_error`` (e.g.
    a 401 or 500). Reuses the tested classifier so the rule stays single-sourced."""
    return classify_run(jsonl_path).status == RATE_LIMITED


def audit_dir(run_dir: Path) -> list[RunAudit]:
    """Classify every ``*_run<N>.jsonl`` transcript under ``run_dir`` (recursive),
    sorted by path for deterministic output.

    Any path component **below** ``run_dir`` that starts with ``_`` is skipped —
    these are meta/sidecar dirs by repo convention (``_driver_logs``,
    ``_quarantine``, ``_analysis``, ``_legacy_*``, ``_NNN_backup_*``). Without
    this, a backup dir of set-aside failures (e.g. ``_401_backup_2026-05-27``)
    would be miscounted as live run data. The top-level ``run_dir`` name itself
    is not subject to this rule, so ``runs/swebench/_analysis/...`` passed
    explicitly still audits."""
    run_dir = Path(run_dir)
    results: list[RunAudit] = []
    for p in sorted(run_dir.rglob("*.jsonl")):
        rel_parts = p.relative_to(run_dir).parts[:-1]  # exclude the filename
        if any(part.startswith("_") for part in rel_parts):
            continue
        if not _STEM_RE.match(p.stem):
            continue
        results.append(classify_run(p))
    return results
