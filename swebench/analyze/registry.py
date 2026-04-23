"""Registry I/O, schema validation, and merge helpers for ``patterns.json``.

``patterns.json`` is the canonical pathology vocabulary for epic #62: it
collects every distinct pathology ``candidate_id`` and its human-readable
description. Tracking metadata (frequency, arm distribution, evidence refs)
lives in the per-run analysis output under ``runs/swebench/_analysis/``,
not here. This module exposes:

- :func:`load_patterns` — read + validate an existing file.
- :func:`write_patterns` — atomic write via ``tmp`` + :func:`os.replace`.
- :func:`validate` — hand-rolled schema validator for the registry file.
- :func:`merge` — pure merge function (append-new-ids semantics).
- :func:`validate_subagent_output` — strict validator for Stage 2 subagent
  JSON replies.

All validators return a list of error strings; an empty list means valid.
This keeps call sites simple (``if errors: refuse(...)``) and lets callers
aggregate multiple problems in a single error message.
"""

from __future__ import annotations

import copy
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

#: Valid arm names for subagent output. Includes both SWE-bench arm names
#: (``baseline``, ``onlycode``) and artifact arm names
#: (``tool_rich``, ``code_only``) so the same validator accepts sidecars
#: from either benchmark.
VALID_ARMS = ("baseline", "onlycode", "tool_rich", "code_only")

#: Valid severity / confidence enum values for subagent findings.
VALID_SEVERITY = ("low", "medium", "high")
VALID_CONFIDENCE = ("low", "medium", "high")

#: ``candidate_id`` slug regex: lowercase alnum + hyphen/underscore, 2–64 chars.
CANDIDATE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")

#: Top-level keys allowed in ``patterns.json``.
_REGISTRY_TOP_KEYS = {"version", "patterns"}

#: Keys allowed on each pattern entry.
_PATTERN_KEYS = {"id", "description"}

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

        ids = [p["id"] for p in data["patterns"]]
        if len(ids) != len(set(ids)):
            dupes = [id for id in ids if ids.count(id) > 1]
            errs.append(f"duplicate pattern ids: {sorted(set(dupes))}")

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
        return errs

    pid = pat["id"]
    if not isinstance(pid, str) or not CANDIDATE_ID_RE.match(pid):
        errs.append(f"{prefix}.id invalid slug: {pid!r}")

    if not isinstance(pat["description"], str):
        errs.append(f"{prefix}.description must be a string")

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


def merge(existing: dict, findings: list[dict]) -> dict:
    """Merge ``findings`` into ``existing`` registry.

    ``findings`` is a flat list of dicts, each carrying at minimum
    ``candidate_id`` and ``description``.

    Pure function: does not mutate ``existing`` or ``findings``. Always
    returns a fresh dict sorted by ``id``.

    Merge rules:
      - Patterns are keyed by ``id``.
      - If ``candidate_id`` matches an existing ``id``: no-op (description
        is first-writer-wins; tracking data lives in the run sidecar).
      - If ``candidate_id`` is new: append ``{id, description}``.
    """
    if existing is None:
        merged = _empty_registry()
    else:
        merged = copy.deepcopy(existing)
        merged.setdefault("version", SCHEMA_VERSION)
        merged.setdefault("patterns", [])

    by_id: dict[str, dict] = {p["id"]: p for p in merged["patterns"]}

    for finding in findings:
        cid = finding.get("candidate_id", "")
        if not cid or cid in by_id:
            continue
        pat = {"id": cid, "description": finding.get("description", "")}
        by_id[cid] = pat
        merged["patterns"].append(pat)

    merged["patterns"] = sorted(merged["patterns"], key=lambda p: p["id"])
    return merged


# ---------------------------------------------------------------------------
# Helper: flatten synthesizer output into merge()-shaped findings.
# ---------------------------------------------------------------------------


def flatten_synth_findings(synth_findings: list[dict]) -> list[dict]:
    """Deduplicate synthesizer findings by ``candidate_id``.

    Returns one entry per distinct ``candidate_id`` carrying ``candidate_id``
    and ``description`` — sufficient for :func:`merge`. Evidence refs and
    arm distribution live in the run sidecar (``synthesizer.json``), not in
    ``patterns.json``.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for f in synth_findings:
        cid = f.get("candidate_id", "")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        out.append({"candidate_id": cid, "description": f.get("description", "")})
    return out


def flatten_findings(subagent_outputs: list[dict]) -> list[dict]:
    """Flatten N validated subagent outputs into a flat list of findings.

    Each output contributes one entry per finding carrying ``candidate_id``
    and ``description``.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for sub in subagent_outputs:
        for f in sub.get("findings", []) or []:
            cid = f.get("candidate_id", "")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            out.append({"candidate_id": cid, "description": f.get("description", "")})
    return out


__all__ = [
    "SCHEMA_VERSION",
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
