"""Hidden grader for stateful_reasoning__unreachable_functions.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    The agent's output/unreachable.jsonl MUST list exactly the functions that
    are unreachable from ``main()`` in ``src/main.py`` via static call-graph
    analysis (BFS over explicit function calls, per-function not per-module).

    Each row MUST carry a ``function`` key (the function name, as defined)
    AND a ``module`` key (the Python module filename without ``.py``, e.g.
    ``utils`` for ``src/utils.py``). The grader walks ``src/*.py``, records
    which file each function was defined in, and validates the agent's
    ``module`` value against that mapping.

    Ground truth is computed by the grader itself using AST analysis — same
    algorithm as the reference solver. Set equality on (function, module)
    pairs.

Determinism: pure AST analysis, no randomness.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


OUTPUT_REL = "output/unreachable.jsonl"
SRC_REL = "src"


def _analyze_reachability(src_dir: Path) -> tuple[set[str], dict[str, str]]:
    """Return ``(unreachable_function_names, function_to_module)``.

    ``function_to_module`` maps every function name in the source tree (not
    just the unreachable ones) to its defining module's stem (the filename
    without the ``.py`` extension). Issue #166 added this second return
    value so :func:`grade` can validate the agent's ``module`` field.
    """
    func_calls: dict[str, set[str]] = {}
    func_to_module: dict[str, str] = {}

    for py_file in sorted(src_dir.glob("*.py")):
        module_name = py_file.stem
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fname = node.name
                calls: set[str] = set()
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Name):
                            calls.add(child.func.id)
                        elif isinstance(child.func, ast.Attribute):
                            calls.add(child.func.attr)
                func_calls[fname] = calls
                func_to_module[fname] = module_name

    all_funcs = set(func_calls.keys())

    reachable: set[str] = {"main"}
    queue = ["main"]
    while queue:
        func = queue.pop(0)
        for called in func_calls.get(func, set()):
            if called in all_funcs and called not in reachable:
                reachable.add(called)
                queue.append(called)

    return all_funcs - reachable, func_to_module


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    output_path = scratch_dir / OUTPUT_REL
    src_dir = scratch_dir / SRC_REL

    if not src_dir.is_dir():
        return GradeResult(False, 0.0, f"src/ directory not found in scratch dir")

    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    raw = output_path.read_text()
    if not raw.strip():
        return GradeResult(False, 0.0, "output artifact is empty")

    agent_funcs: set[str] = set()
    # function_name -> module string the agent claimed for it
    agent_func_to_module: dict[str, str] = {}
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            return GradeResult(False, 0.0, f"line {lineno}: JSON parse error: {exc.msg}")
        if not isinstance(obj, dict):
            return GradeResult(False, 0.0, f"line {lineno}: expected JSON object")
        if "function" not in obj:
            return GradeResult(False, 0.0, f"line {lineno}: missing 'function' key")
        # Issue #166: validate the ``module`` field — previously parsed but
        # unchecked, allowing rows with missing/wrong module values to pass.
        if "module" not in obj:
            return GradeResult(False, 0.0, f"line {lineno}: missing 'module' key")
        fname = obj["function"]
        mod = obj["module"]
        if not isinstance(fname, str):
            return GradeResult(False, 0.0, f"line {lineno}: 'function' must be a string")
        if not isinstance(mod, str):
            return GradeResult(False, 0.0, f"line {lineno}: 'module' must be a string")
        if fname in agent_funcs:
            return GradeResult(False, 0.0, f"duplicate function name: {fname!r}")
        agent_funcs.add(fname)
        agent_func_to_module[fname] = mod

    reference, func_to_module = _analyze_reachability(src_dir)

    missing = reference - agent_funcs
    extra = agent_funcs - reference

    if missing or extra:
        parts = []
        if missing:
            parts.append(f"missing {len(missing)} function(s): {sorted(missing)}")
        if extra:
            parts.append(f"{len(extra)} incorrect function(s) in output: {sorted(extra)}")
        return GradeResult(
            False,
            round(len(agent_funcs & reference) / max(len(reference), 1), 4),
            "; ".join(parts),
        )

    # Issue #166: validate ``module`` against the file each function was
    # defined in (collected during the AST walk above).
    wrong_module: list[str] = []
    for fname in sorted(reference):
        expected_mod = func_to_module.get(fname)
        agent_mod = agent_func_to_module.get(fname)
        if expected_mod is None:
            # Should not happen: ``reference`` is a subset of all_funcs, and
            # all_funcs keys are populated from the same walk.
            continue
        if agent_mod != expected_mod:
            wrong_module.append(fname)

    if wrong_module:
        return GradeResult(False, 0.0,
            f"wrong 'module' value on {len(wrong_module)} function(s): "
            f"{sorted(wrong_module)[:5]}")

    return GradeResult(True, 1.0,
        f"all {len(reference)} unreachable functions identified correctly, "
        f"with matching module values")
