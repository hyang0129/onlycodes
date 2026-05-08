"""Shared helpers for the artifact-grader **negative** sanity check.

SCHEMA_ARTIFACT.md §5.4 specifies a positive sanity check: a task's
``reference_output`` should produce ``passed=True, score=1.0`` when fed back
into its grader. That check catches graders that reject their own known-good
answer, but it cannot catch a different — and just as common — silent failure:
a grader that *accepts* artifacts it should reject because the prompt's
correctness criterion was incompletely encoded.

This module is the framework half of the negative sanity check (§5.5). It
defines:

* :class:`NegativeCase` — one negative-test entry: a name, a mutation function
  applied to the reference-output bytes, and (optionally) a substring expected
  to appear in the grader's ``detail`` field on rejection.
* :func:`default_negative_cases` — six standard mutations every task gets for
  free (empty, truncated, reversed-lines, renamed-required-field, off-by-one
  numeric, wrap-in-list).
* :func:`load_task_negative_cases` — discovery: per-task ``grader/negative_cases.py``
  may export a ``NEGATIVE_CASES`` list; if it does we use that, else we fall
  back to :func:`default_negative_cases`.
* :func:`run_negative_case` — execute one mutation: materialize the workspace,
  write the mutated artifact, invoke the grader, and report whether the
  grader correctly rejected it.

Authors of new tasks are encouraged but NOT required to ship a per-task
``negative_cases.py``: the default cases catch the most common shape failures.
A task author who knows the prompt encodes a property the default mutations
do not exercise (sort order, optional fields, set vs. list semantics, …)
SHOULD add a per-task case for that property.

Cross-references:
  - ``tools/check_grader_negative.py`` — the CLI driver that uses this module.
  - ``tools/verify_graders.py`` — the existing positive sanity check.
  - ``docs/SCHEMA_ARTIFACT.md`` §5.5 — the contract this module implements.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from swebench.artifact_grade import GraderInvocationError, invoke_grader
from swebench.artifact_materialize import materialize
from swebench.artifact_models import GradeResult, Task


# ─────────────────────────── data model ────────────────────────────────────


@dataclass(frozen=True)
class NegativeCase:
    """One deliberately-wrong artifact that the grader is expected to reject.

    Attributes:
        name: Short identifier used in CLI output (e.g. ``"empty"``,
            ``"reversed_lines"``). Should be unique within a task's case list.
        mutate: Callable that takes the reference-output bytes (as ``str``)
            and returns a mutated string. Returning the input unchanged is
            allowed but pointless — such a case is silently treated as a no-op.
        expected_substring: Optional case-insensitive substring expected in the
            grader's ``detail`` field. Empty string means "any rejection is
            fine, just check ``passed=False``". Author-supplied substrings
            help catch graders that reject for the *wrong* reason (e.g. an
            empty-file shortcut firing before the correctness check).
        currently_caught: ``True`` when today's grader is expected to reject
            this mutation. ``False`` is reserved for cases that document a
            known grader-vs-prompt alignment bug — the negative case fires
            but the grader incorrectly passes. The driver prints WARNING for
            ``False`` cases and continues; flipping to ``True`` lands as part
            of the bug-fix PR.
        notes: Free-form annotation. Often a GitHub issue link explaining why
            ``currently_caught`` is ``False``.
    """

    name: str
    mutate: Callable[[str], str]
    expected_substring: str = ""
    currently_caught: bool = True
    notes: str = ""


# ───────────────────────── default mutations ───────────────────────────────


def _mutate_empty(text: str) -> str:
    """Replace artifact with empty string."""
    del text
    return ""


def _mutate_truncate_half(text: str) -> str:
    """Keep the first 50% of the bytes (rounded down)."""
    return text[: len(text) // 2]


def _mutate_reverse_lines(text: str) -> str:
    """Reverse the order of non-empty lines (catches missing order checks).

    Preserves a trailing newline if the original had one. Strips blank lines
    so a final blank doesn't become a leading blank after the reverse.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) <= 1:
        # Single-line / empty inputs aren't useful for an order check; return
        # something *visibly* mutated so the grader has a chance to fail.
        return text + text
    reversed_text = "\n".join(reversed(lines))
    if text.endswith("\n"):
        reversed_text += "\n"
    return reversed_text


_RENAME_PATTERNS = (
    # Quoted JSON keys are the most common shape ("foo":).
    (re.compile(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*:'), True),
)


def _mutate_rename_one_field(text: str) -> str:
    """Rename the first JSON key encountered to a guaranteed-wrong name.

    Picks the first match of ``"<name>":`` in the text and renames it to
    ``"<name>_was_renamed"``. Renames every occurrence of that exact key to
    keep the document internally consistent (so a grader that fails on
    "missing key X" fails for *that* reason, not a JSON parse error).

    Falls back to a byte-flip suffix mutation if no JSON key is found
    (some artifacts are plain text or CSV).
    """
    for pat, _ in _RENAME_PATTERNS:
        match = pat.search(text)
        if match:
            old = match.group(1)
            new = f"{old}_renamed"
            # Replace every "<old>": in the text with "<new>":.
            target = f'"{old}":'
            replacement = f'"{new}":'
            # Most graders don't care about whitespace; use a regex to be
            # defensive against "foo" : (with space).
            return re.sub(
                r'"' + re.escape(old) + r'"\s*:',
                replacement,
                text,
            )
    # Plain-text fallback: append a marker that's likely to fail any
    # length / row-count check.
    return text + "RENAMED_FIELD_MUTATION_TAIL\n"


_NUMERIC_RE = re.compile(r"(-?\d+\.\d+|-?\d+)")


def _mutate_off_by_one(text: str) -> str:
    """Add 1 to the first numeric literal in the text.

    Catches graders that forgot to verify a numeric field. The mutation is
    arithmetic, not lexical: a value like ``42`` becomes ``43``; ``3.14``
    becomes ``4.14``. We only mutate the FIRST match because mutating every
    number would push the artifact so far out of shape that *some other*
    check would fire first.
    """
    match = _NUMERIC_RE.search(text)
    if not match:
        return text + "1"
    raw = match.group(0)
    try:
        if "." in raw:
            # Preserve the number of fractional digits so floating-point
            # noise (e.g. ``3.14 + 1.0 -> 4.140000000000001``) does not
            # leak into the artifact.
            decimals = len(raw.split(".", 1)[1])
            new_val = f"{float(raw) + 1.0:.{decimals}f}"
        else:
            new_val = str(int(raw) + 1)
    except ValueError:  # pragma: no cover — regex guarantees parseable
        return text
    start, end = match.span()
    return text[:start] + new_val + text[end:]


def _mutate_wrap_in_list(text: str) -> str:
    """Wrap the artifact in a JSON list literal.

    Catches graders that don't validate top-level shape (e.g. they parse
    each line of a JSONL file but never check that the file is JSONL and
    not, say, a single JSON array).
    """
    return f"[{text}]"


def default_negative_cases() -> list[NegativeCase]:
    """Six task-agnostic negative cases applied to every grader by default.

    Order is stable so the CLI output is reproducible.
    """
    return [
        NegativeCase(
            name="empty",
            mutate=_mutate_empty,
            expected_substring="",  # any rejection is fine
            currently_caught=True,
        ),
        NegativeCase(
            name="truncated_half",
            mutate=_mutate_truncate_half,
            expected_substring="",
            currently_caught=True,
        ),
        NegativeCase(
            name="reversed_lines",
            mutate=_mutate_reverse_lines,
            expected_substring="",
            currently_caught=True,
        ),
        NegativeCase(
            name="renamed_field",
            mutate=_mutate_rename_one_field,
            expected_substring="",
            currently_caught=True,
        ),
        NegativeCase(
            name="off_by_one",
            mutate=_mutate_off_by_one,
            expected_substring="",
            currently_caught=True,
        ),
        NegativeCase(
            name="wrap_in_list",
            mutate=_mutate_wrap_in_list,
            expected_substring="",
            currently_caught=True,
        ),
    ]


# ─────────────────────────── per-task discovery ────────────────────────────


def load_task_negative_cases(task: Task) -> tuple[list[NegativeCase], bool]:
    """Return ``(cases, is_custom)`` for ``task``.

    ``is_custom`` is ``True`` when the task ships ``grader/negative_cases.py``
    and the module exposes a non-None ``NEGATIVE_CASES`` list. ``False``
    means the caller is using :func:`default_negative_cases` as a
    diagnostic fallback. Callers SHOULD pass ``is_custom`` through to
    :func:`run_negative_case` as ``from_defaults`` (inverted) so the
    distinction shows up in outcome statuses.

    The custom module is loaded by file path so the task tree does not need
    to be on ``sys.path``. The ``swebench.artifact_negative`` module is
    placed on ``sys.path`` at import time, so a task module can simply
    ``from swebench.artifact_negative import NegativeCase``.
    """
    if task.task_dir is None:
        raise ValueError(f"Task {task.instance_id!r} has no task_dir attached")
    candidate = task.task_dir / "grader" / "negative_cases.py"
    if not candidate.is_file():
        return default_negative_cases(), False

    module_name = f"_negative_cases_{task.instance_id}"
    spec = importlib.util.spec_from_file_location(module_name, candidate)
    if spec is None or spec.loader is None:  # pragma: no cover — defensive
        raise ImportError(f"Could not load {candidate}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    cases = getattr(module, "NEGATIVE_CASES", None)
    if cases is None:
        # Module exists but is silent — treat as opt-in to defaults.
        return default_negative_cases(), False
    if not isinstance(cases, list) or not all(isinstance(c, NegativeCase) for c in cases):
        raise TypeError(
            f"{candidate}: NEGATIVE_CASES must be list[NegativeCase], "
            f"got {type(cases).__name__}"
        )
    return list(cases), True


# ─────────────────────────── case execution ────────────────────────────────


@dataclass
class NegativeCaseOutcome:
    """Result of running one :class:`NegativeCase` against one task."""

    task_id: str
    case_name: str
    status: str
    # Status codes:
    #   "PASS"           — grader correctly rejected the mutated artifact.
    #   "MISS"           — grader accepted a mutated artifact from a CUSTOM
    #                      per-task case. Hard failure.
    #   "WEAK_MISS"      — grader accepted a mutated artifact from a DEFAULT
    #                      mutation. Diagnostic only — surfaces alignment
    #                      bugs in tasks that haven't yet shipped a custom
    #                      grader/negative_cases.py. Does not fail CI.
    #   "WRONG_REASON"   — grader rejected, but detail did not contain the
    #                      expected substring. Soft failure when from a
    #                      custom case (graders rejecting for the wrong
    #                      reason are a real bug); diagnostic-only when from
    #                      a default mutation.
    #   "EXPECTED_MISS"  — grader accepted, AND the case was annotated
    #                      ``currently_caught=False``. Warning only.
    #   "ERROR"          — infrastructure failure.
    detail: str = ""
    grade_result: GradeResult | None = None
    from_defaults: bool = False

    @property
    def is_failure(self) -> bool:
        """True when this outcome should make the CLI exit non-zero.

        ``WEAK_MISS`` and a ``WRONG_REASON`` from a default mutation are
        diagnostic only — they reveal alignment bugs in tasks that haven't
        yet been audited and should not break CI on the framework PR.
        Promoting the finding to a custom case (with appropriate
        ``currently_caught=False`` annotation) is the documented path to
        track such bugs.
        """
        if self.status in {"MISS", "ERROR"}:
            return True
        if self.status == "WRONG_REASON" and not self.from_defaults:
            return True
        return False


def run_negative_case(
    task: Task,
    case: NegativeCase,
    *,
    grader_timeout_seconds: float | None = 120.0,
    from_defaults: bool = False,
) -> NegativeCaseOutcome:
    """Run one negative case end-to-end.

    Steps:
        1. Materialize the task workspace into a temp scratch dir.
        2. Read the reference output, apply ``case.mutate``.
        3. Write the mutated bytes to ``scratch / output_artifact``.
        4. Invoke the grader.
        5. Map the result to a :class:`NegativeCaseOutcome`.

    Status semantics:
        * ``PASS`` — grader returned ``passed=False`` and (if the case
          declared one) the detail substring matched. This is the desired
          outcome.
        * ``MISS`` — grader returned ``passed=True``. The mutation slipped
          through. **This is a real failure** unless the case is annotated
          ``currently_caught=False`` (in which case the status is
          ``EXPECTED_MISS``).
        * ``WRONG_REASON`` — grader returned ``passed=False`` but the
          detail did NOT contain the expected substring. The grader rejected
          the artifact, but for a different reason than the case targeted.
          Often indicates a structural shortcut firing before the
          correctness check.
        * ``EXPECTED_MISS`` — grader returned ``passed=True`` AND the case
          was annotated ``currently_caught=False``. Treated as a known bug
          (warning, but exit zero).
        * ``ERROR`` — infrastructure failure (missing reference, bad
          materialization, grader raised).
    """
    if task.task_dir is None:
        return NegativeCaseOutcome(
            task_id=task.instance_id,
            case_name=case.name,
            status="ERROR",
            detail="task_dir not set",
            from_defaults=from_defaults,
        )

    ref_path = task.task_dir / task.reference_output
    if not ref_path.is_file():
        return NegativeCaseOutcome(
            task_id=task.instance_id,
            case_name=case.name,
            status="ERROR",
            detail=f"reference_output not found: {ref_path}",
            from_defaults=from_defaults,
        )

    try:
        original = ref_path.read_text()
    except OSError as exc:
        return NegativeCaseOutcome(
            task_id=task.instance_id,
            case_name=case.name,
            status="ERROR",
            detail=f"could not read reference_output: {exc}",
            from_defaults=from_defaults,
        )

    try:
        mutated = case.mutate(original)
    except Exception as exc:  # noqa: BLE001 — author code, surface anything
        return NegativeCaseOutcome(
            task_id=task.instance_id,
            case_name=case.name,
            status="ERROR",
            detail=f"mutate({case.name}) raised: {exc!r}",
            from_defaults=from_defaults,
        )

    if mutated == original:
        # A no-op mutation gives no signal — flag explicitly rather than
        # let it look like a successful negative test.
        return NegativeCaseOutcome(
            task_id=task.instance_id,
            case_name=case.name,
            status="ERROR",
            detail="mutation produced unchanged output (no-op)",
            from_defaults=from_defaults,
        )

    with tempfile.TemporaryDirectory(prefix="check_grader_negative_") as tmp:
        scratch = Path(tmp) / "scratch"
        try:
            materialize(task, scratch)
        except Exception as exc:  # noqa: BLE001 — surface materialization errors
            return NegativeCaseOutcome(
                task_id=task.instance_id,
                case_name=case.name,
                status="ERROR",
                detail=f"workspace materialization failed: {exc}",
                from_defaults=from_defaults,
            )

        dest = scratch / task.output_artifact
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(mutated)

        try:
            result = invoke_grader(task, scratch, timeout_seconds=grader_timeout_seconds)
        except GraderInvocationError as exc:
            return NegativeCaseOutcome(
                task_id=task.instance_id,
                case_name=case.name,
                status="ERROR",
                detail=str(exc),
                from_defaults=from_defaults,
            )

    if result.passed:
        # The grader accepted a deliberately-wrong artifact.
        if not case.currently_caught:
            return NegativeCaseOutcome(
                task_id=task.instance_id,
                case_name=case.name,
                status="EXPECTED_MISS",
                detail=(
                    f"known unfixed grader bug; passed=True; "
                    f"detail={result.detail!r}; notes={case.notes!r}"
                ),
                grade_result=result,
                from_defaults=from_defaults,
            )
        # Hard MISS for custom cases; WEAK_MISS (diagnostic) for defaults.
        status = "WEAK_MISS" if from_defaults else "MISS"
        return NegativeCaseOutcome(
            task_id=task.instance_id,
            case_name=case.name,
            status=status,
            detail=(
                f"grader incorrectly returned passed=True; "
                f"detail={result.detail!r}"
            ),
            grade_result=result,
            from_defaults=from_defaults,
        )

    # Grader rejected. Optional substring check.
    if case.expected_substring:
        if case.expected_substring.lower() not in result.detail.lower():
            return NegativeCaseOutcome(
                task_id=task.instance_id,
                case_name=case.name,
                status="WRONG_REASON",
                detail=(
                    f"expected detail to contain "
                    f"{case.expected_substring!r}; got {result.detail!r}"
                ),
                grade_result=result,
                from_defaults=from_defaults,
            )

    return NegativeCaseOutcome(
        task_id=task.instance_id,
        case_name=case.name,
        status="PASS",
        detail=result.detail,
        grade_result=result,
        from_defaults=from_defaults,
    )


def run_all_for_task(
    task: Task,
    cases: Iterable[NegativeCase] | None = None,
    *,
    grader_timeout_seconds: float | None = 120.0,
    from_defaults: bool | None = None,
) -> list[NegativeCaseOutcome]:
    """Run every negative case for one task and return the outcomes.

    If ``cases`` is None, the per-task list is loaded via
    :func:`load_task_negative_cases` and ``from_defaults`` is inferred. If
    ``cases`` is provided explicitly, ``from_defaults`` defaults to ``False``
    (the caller is making a deliberate choice; treat as custom unless
    overridden).
    """
    if cases is None:
        cases, is_custom = load_task_negative_cases(task)
        inferred_from_defaults = not is_custom
        if from_defaults is None:
            from_defaults = inferred_from_defaults
    else:
        cases = list(cases)
        if from_defaults is None:
            from_defaults = False
    return [
        run_negative_case(
            task,
            c,
            grader_timeout_seconds=grader_timeout_seconds,
            from_defaults=from_defaults,
        )
        for c in cases
    ]


__all__ = [
    "NegativeCase",
    "NegativeCaseOutcome",
    "default_negative_cases",
    "load_task_negative_cases",
    "run_all_for_task",
    "run_negative_case",
]
