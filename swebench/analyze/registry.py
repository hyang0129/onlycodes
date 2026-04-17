"""Registry I/O, schema validation, and merge helpers for ``patterns.json``.

``patterns.json`` is the canonical pathology vocabulary for epic #62: it
collects every distinct pathology ``candidate_id`` observed across analysis
runs along with evidence references, per-arm frequency, and first/last-seen
run identifiers. This module exposes:

- :func:`load_patterns` — read + validate an existing file.
- :func:`write_patterns` — atomic write via ``tmp`` + :func:`os.replace`.
- :func:`validate` — hand-rolled schema validator for the registry file.
- :func:`merge` — pure merge function (append-merge semantics, ADR Q5).
- :func:`validate_subagent_output` — strict validator for Stage 2 subagent
  JSON replies.

All validators return a list of error strings; an empty list means valid.
This keeps call sites simple (``if errors: refuse(...)``) and lets callers
aggregate multiple problems in a single error message.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Current registry schema version. Incremented only on breaking change.
SCHEMA_VERSION = 1

#: Cap on ``evidence_refs`` per pattern. See ADR merge rule 1.
MAX_EVIDENCE_REFS = 20

#: Valid arm names for ``arm_distribution`` and subagent output.
VALID_ARMS = ("baseline", "onlycode")

#: Valid severity / confidence enum values for subagent findings.
VALID_SEVERITY = ("low", "medium", "high")
VALID_CONFIDENCE = ("low", "medium", "high")

#: ``candidate_id`` slug regex: lowercase alnum + hyphen/underscore, 2–64 chars.
CANDIDATE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")

#: Top-level keys allowed in ``patterns.json``.
_REGISTRY_TOP_KEYS = {"version", "patterns"}

#: Keys allowed on each pattern entry.
_PATTERN_KEYS = {
    "id",
    "description",
    "evidence_refs",
    "frequency",
    "arm_distribution",
    "first_seen_run_id",
    "last_seen_run_id",
}

#: Keys allowed on each evidence_ref entry in the registry.
_REGISTRY_EVIDENCE_KEYS = {"log_ref", "run_id", "turn", "excerpt"}

#: Top-level keys allowed in subagent JSON output.
_SUBAGENT_TOP_KEYS = {"log_ref", "arm", "findings", "notes"}

#: Keys allowed per finding in subagent output.
_FINDING_KEYS = {
    "candidate_id",
    "description",
    "evidence_refs",
    "severity",
    "confidence",
}


# ---------------------------------------------------------------------------
# Schema validation — registry file
# ---------------------------------------------------------------------------


def validate(data: Any) -> list[str]:
    """Validate a decoded ``patterns.json`` payload.

    Returns a list of human-readable error strings. An empty list means the
    payload is a well-formed v1 registry.
    """
    errs: list[str] = []
    if not isinstance(data, dict):
        return ["top-level value must be an object"]

    unknown = set(data.keys()) - _REGISTRY_TOP_KEYS
    if unknown:
        errs.append(f"unknown top-level keys: {sorted(unknown)}")

    if "version" not in data:
        errs.append("missing key: version")
    elif data["version"] != SCHEMA_VERSION:
        errs.append(f"unsupported version: {data['version']} (expected {SCHEMA_VERSION})")

    if "patterns" not in data:
        errs.append("missing key: patterns")
    elif not isinstance(data["patterns"], list):
        errs.append("patterns must be a list")
    else:
        for i, pat in enumerate(data["patterns"]):
            errs.extend(_validate_pattern(pat, i))

    return errs


def _validate_pattern(pat: Any, idx: int) -> list[str]:
    prefix = f"patterns[{idx}]"
    errs: list[str] = []
    if not isinstance(pat, dict):
        return [f"{prefix} must be an object"]

    unknown = set(pat.keys()) - _PATTERN_KEYS
    if unknown:
        errs.append(f"{prefix} has unknown keys: {sorted(unknown)}")

    missing = _PATTERN_KEYS - set(pat.keys())
    if missing:
        errs.append(f"{prefix} missing keys: {sorted(missing)}")
        return errs  # further checks would cascade

    pid = pat["id"]
    if not isinstance(pid, str) or not CANDIDATE_ID_RE.match(pid):
        errs.append(f"{prefix}.id invalid slug: {pid!r}")

    if not isinstance(pat["description"], str):
        errs.append(f"{prefix}.description must be a string")

    ev = pat["evidence_refs"]
    if not isinstance(ev, list):
        errs.append(f"{prefix}.evidence_refs must be a list")
    else:
        if len(ev) > MAX_EVIDENCE_REFS:
            errs.append(
                f"{prefix}.evidence_refs exceeds cap {MAX_EVIDENCE_REFS} (got {len(ev)})"
            )
        for j, ref in enumerate(ev):
            errs.extend(_validate_evidence_ref(ref, f"{prefix}.evidence_refs[{j}]"))

    if not isinstance(pat["frequency"], int) or pat["frequency"] < 0:
        errs.append(f"{prefix}.frequency must be a non-negative int")

    ad = pat["arm_distribution"]
    if not isinstance(ad, dict):
        errs.append(f"{prefix}.arm_distribution must be an object")
    else:
        ad_unknown = set(ad.keys()) - set(VALID_ARMS)
        if ad_unknown:
            errs.append(f"{prefix}.arm_distribution has unknown arms: {sorted(ad_unknown)}")
        for arm in VALID_ARMS:
            if arm in ad and (not isinstance(ad[arm], int) or ad[arm] < 0):
                errs.append(f"{prefix}.arm_distribution.{arm} must be a non-negative int")

    for key in ("first_seen_run_id", "last_seen_run_id"):
        if not isinstance(pat[key], str) or not pat[key]:
            errs.append(f"{prefix}.{key} must be a non-empty string")

    return errs


def _validate_evidence_ref(ref: Any, prefix: str) -> list[str]:
    errs: list[str] = []
    if not isinstance(ref, dict):
        return [f"{prefix} must be an object"]
    unknown = set(ref.keys()) - _REGISTRY_EVIDENCE_KEYS
    if unknown:
        errs.append(f"{prefix} has unknown keys: {sorted(unknown)}")
    missing = _REGISTRY_EVIDENCE_KEYS - set(ref.keys())
    if missing:
        errs.append(f"{prefix} missing keys: {sorted(missing)}")
        return errs
    if not isinstance(ref["log_ref"], str):
        errs.append(f"{prefix}.log_ref must be a string")
    if not isinstance(ref["run_id"], str):
        errs.append(f"{prefix}.run_id must be a string")
    if not isinstance(ref["turn"], int):
        errs.append(f"{prefix}.turn must be an int")
    if not isinstance(ref["excerpt"], str):
        errs.append(f"{prefix}.excerpt must be a string")
    elif len(ref["excerpt"]) > 240:
        errs.append(f"{prefix}.excerpt exceeds 240 chars")
    return errs


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


def load_patterns(path: Path) -> tuple[dict | None, str | None]:
    """Load and validate ``patterns.json`` at ``path``.

    Returns ``(data, None)`` on success, or ``(None, reason)`` on any of:
    file missing, JSON decode failure, schema validation failure.
    """
    if not path.exists():
        return (None, f"{path} does not exist")
    try:
        raw = path.read_text()
    except OSError as exc:
        return (None, f"read failed: {exc}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return (None, f"JSON decode failed: {exc}")
    errs = validate(data)
    if errs:
        return (None, "; ".join(errs))
    return (data, None)


def write_patterns(path: Path, data: dict) -> None:
    """Atomically write ``data`` as formatted JSON to ``path``.

    Writes to a sibling tempfile in the same directory and uses
    :func:`os.replace` to swap — guaranteeing the destination is either the
    full prior content or the full new content, never a partial write.
    Patterns are sorted by ``id`` as a side effect for deterministic output.
    """
    if "patterns" in data and isinstance(data["patterns"], list):
        data = {**data, "patterns": sorted(data["patterns"], key=lambda p: p.get("id", ""))}
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write to sibling tempfile in the same directory so os.replace is atomic
    # (same filesystem guarantee).
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=".patterns-", suffix=".json.tmp", dir=str(path.parent)
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        # Clean up the tmp file on failure; swallow cleanup errors.
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Subagent output validation
# ---------------------------------------------------------------------------


def validate_subagent_output(data: Any) -> list[str]:
    """Strict validator for a single subagent's JSON reply.

    See ``swebench/analyze/subagent_prompt.md`` for the expected schema.
    Returns a list of error strings; empty = valid. Unknown keys at either
    the top level or inside a finding are rejected.
    """
    errs: list[str] = []
    if not isinstance(data, dict):
        return ["top-level value must be an object"]

    unknown = set(data.keys()) - _SUBAGENT_TOP_KEYS
    if unknown:
        errs.append(f"unknown top-level keys: {sorted(unknown)}")

    for req in ("log_ref", "arm", "findings"):
        if req not in data:
            errs.append(f"missing key: {req}")

    if "log_ref" in data and not isinstance(data["log_ref"], str):
        errs.append("log_ref must be a string")
    if "arm" in data:
        if not isinstance(data["arm"], str) or data["arm"] not in VALID_ARMS:
            errs.append(f"arm must be one of {VALID_ARMS}")
    if "notes" in data and not isinstance(data["notes"], str):
        errs.append("notes must be a string if present")

    findings = data.get("findings")
    if findings is not None:
        if not isinstance(findings, list):
            errs.append("findings must be a list")
        else:
            for i, f in enumerate(findings):
                errs.extend(_validate_finding(f, f"findings[{i}]"))

    return errs


def _validate_finding(f: Any, prefix: str) -> list[str]:
    errs: list[str] = []
    if not isinstance(f, dict):
        return [f"{prefix} must be an object"]

    unknown = set(f.keys()) - _FINDING_KEYS
    if unknown:
        errs.append(f"{prefix} has unknown keys: {sorted(unknown)}")
    missing = _FINDING_KEYS - set(f.keys())
    if missing:
        errs.append(f"{prefix} missing keys: {sorted(missing)}")
        return errs

    cid = f["candidate_id"]
    if not isinstance(cid, str) or not CANDIDATE_ID_RE.match(cid):
        errs.append(f"{prefix}.candidate_id invalid slug: {cid!r}")
    if not isinstance(f["description"], str):
        errs.append(f"{prefix}.description must be a string")
    if not isinstance(f["evidence_refs"], list):
        errs.append(f"{prefix}.evidence_refs must be a list")
    else:
        for j, ref in enumerate(f["evidence_refs"]):
            if not isinstance(ref, dict):
                errs.append(f"{prefix}.evidence_refs[{j}] must be an object")
    if f["severity"] not in VALID_SEVERITY:
        errs.append(f"{prefix}.severity must be one of {VALID_SEVERITY}")
    if f["confidence"] not in VALID_CONFIDENCE:
        errs.append(f"{prefix}.confidence must be one of {VALID_CONFIDENCE}")
    return errs


# ---------------------------------------------------------------------------
# Merge (pure)
# ---------------------------------------------------------------------------


def _empty_registry() -> dict:
    return {"version": SCHEMA_VERSION, "patterns": []}


def _blank_pattern(cid: str, description: str, run_id: str) -> dict:
    return {
        "id": cid,
        "description": description,
        "evidence_refs": [],
        "frequency": 0,
        "arm_distribution": {arm: 0 for arm in VALID_ARMS},
        "first_seen_run_id": run_id,
        "last_seen_run_id": run_id,
    }


def _dedup_key(ref: dict) -> tuple[str, str, int]:
    return (ref.get("log_ref", ""), ref.get("run_id", ""), int(ref.get("turn", -1)))


def merge(existing: dict, findings: list[dict], run_id: str) -> dict:
    """Merge ``findings`` (subagent output rows) into ``existing`` registry.

    ``findings`` is a flat list of dicts, each of the shape produced by
    :func:`_flatten_findings` below — i.e. one dict per (subagent_output,
    finding) pair, carrying ``candidate_id``, ``description``, ``log_ref``,
    ``arm``, and a list of subagent-level ``evidence_refs``.

    Pure function: does not mutate ``existing`` or ``findings``. Always
    returns a fresh dict. Patterns in the returned registry are sorted by
    ``id`` deterministically.

    Merge rules (ADR Q5):
      - Patterns are keyed by ``id``.
      - If ``candidate_id`` matches an existing ``id``:
          * frequency += 1 per new evidence_ref (de-duped by
            ``(log_ref, run_id, turn)``)
          * ``arm_distribution[arm]`` += 1 per new evidence_ref
          * evidence_refs appended, bounded to MAX_EVIDENCE_REFS
            (most-recent-first; oldest dropped)
          * ``last_seen_run_id`` = ``run_id``
          * description is NOT updated (first-writer-wins)
      - If ``candidate_id`` is new: insert a fresh pattern and increment
        as above (initial frequency counts from evidence refs).
    """
    # Deep-copy existing via JSON round-trip (small data, keeps it pure).
    if existing is None:
        merged = _empty_registry()
    else:
        merged = json.loads(json.dumps(existing))
        # Tolerate a missing or incomplete skeleton.
        merged.setdefault("version", SCHEMA_VERSION)
        merged.setdefault("patterns", [])

    by_id: dict[str, dict] = {p["id"]: p for p in merged["patterns"]}

    for finding in findings:
        cid = finding["candidate_id"]
        description = finding.get("description", "")
        arm = finding.get("arm", "")
        log_ref = finding.get("log_ref", "")
        # The finding carries subagent-level evidence refs (turn/excerpt).
        # We promote them to registry-level refs by attaching log_ref/run_id.
        new_refs: list[dict] = []
        for r in finding.get("evidence_refs", []) or []:
            new_refs.append(
                {
                    "log_ref": log_ref,
                    "run_id": run_id,
                    "turn": int(r.get("turn", 0)),
                    "excerpt": str(r.get("excerpt", ""))[:240],
                }
            )

        if cid in by_id:
            pat = by_id[cid]
        else:
            pat = _blank_pattern(cid, description, run_id)
            by_id[cid] = pat
            merged["patterns"].append(pat)

        # De-dup against existing refs on this pattern.
        existing_keys = {_dedup_key(r) for r in pat["evidence_refs"]}
        added = 0
        # Prepend new refs most-recent-first (matches the "bounded, most-recent-first" rule).
        for ref in new_refs:
            if _dedup_key(ref) in existing_keys:
                continue
            pat["evidence_refs"].insert(0, ref)
            existing_keys.add(_dedup_key(ref))
            added += 1
            if arm in pat["arm_distribution"]:
                pat["arm_distribution"][arm] += 1
            else:
                # An unexpected arm slipped through validation — be strict.
                pat["arm_distribution"][arm] = pat["arm_distribution"].get(arm, 0) + 1

        pat["frequency"] = pat.get("frequency", 0) + added
        # Stamp last_seen_run_id whenever this finding touched the pattern,
        # regardless of whether any new evidence ref survived de-dup — the
        # mere fact that the pattern re-surfaced in this run is meaningful.
        pat["last_seen_run_id"] = run_id

        # Cap evidence_refs; drop oldest (end of list).
        if len(pat["evidence_refs"]) > MAX_EVIDENCE_REFS:
            pat["evidence_refs"] = pat["evidence_refs"][:MAX_EVIDENCE_REFS]

    merged["patterns"] = sorted(merged["patterns"], key=lambda p: p["id"])
    return merged


# ---------------------------------------------------------------------------
# Helper: flatten a list of subagent outputs into merge()-shaped findings.
# ---------------------------------------------------------------------------


def flatten_findings(subagent_outputs: list[dict]) -> list[dict]:
    """Flatten N validated subagent outputs into a flat list of findings.

    Each output contributes one entry per finding, carrying the parent's
    ``log_ref`` and ``arm`` so :func:`merge` can write evidence-ref context.
    """
    out: list[dict] = []
    for sub in subagent_outputs:
        log_ref = sub.get("log_ref", "")
        arm = sub.get("arm", "")
        for f in sub.get("findings", []) or []:
            out.append(
                {
                    "candidate_id": f["candidate_id"],
                    "description": f.get("description", ""),
                    "evidence_refs": f.get("evidence_refs", []) or [],
                    "log_ref": log_ref,
                    "arm": arm,
                }
            )
    return out


def flatten_synth_findings(synth_findings: list[dict]) -> list[dict]:
    """Convert synthesizer output into :func:`merge`-compatible flat findings.

    Synthesizer evidence_refs carry ``log_ref`` and ``arm`` per ref (a single
    pattern aggregates evidence across multiple logs/arms).  We fan out each
    finding into one entry per distinct ``(log_ref, arm)`` pair so
    :func:`merge` can correctly populate ``arm_distribution`` and
    ``evidence_refs``.  Evidence refs for unrecognised arms are dropped so
    they never reach the schema validator.
    """
    from collections import defaultdict  # local to avoid circular imports

    out: list[dict] = []
    for f in synth_findings:
        cid = f.get("candidate_id", "")
        desc = f.get("description", "")
        refs = f.get("evidence_refs", []) or []

        by_source: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for r in refs:
            arm = r.get("arm", "")
            log_ref = r.get("log_ref", "")
            if arm not in VALID_ARMS:
                continue  # drop unrecognised arms silently
            by_source[(log_ref, arm)].append(r)

        if not by_source:
            continue  # nothing usable — skip this finding entirely

        for (log_ref, arm), source_refs in by_source.items():
            out.append(
                {
                    "candidate_id": cid,
                    "description": desc,
                    "log_ref": log_ref,
                    "arm": arm,
                    "evidence_refs": source_refs,
                }
            )
    return out


__all__ = [
    "SCHEMA_VERSION",
    "MAX_EVIDENCE_REFS",
    "VALID_ARMS",
    "CANDIDATE_ID_RE",
    "load_patterns",
    "write_patterns",
    "validate",
    "validate_subagent_output",
    "merge",
    "flatten_findings",
    "flatten_synth_findings",
]
