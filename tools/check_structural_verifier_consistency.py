#!/usr/bin/env python3
"""Consistency gate for ``structural_verifier`` declarations.

Per ``docs/SCHEMA_ARTIFACT.md`` §2.2 and §4, the ``structural_verifier``
field in ``task.yaml`` is optional, but when a task ships
``workspace/verify.py`` the field MUST be declared (and conversely, a
task that declares the field MUST ship the file).

This lint walks ``problems/artifact/<category>/<slug>/`` and flags two
classes of inconsistency:

  * ``MISSING_DECLARATION`` — ``workspace/verify.py`` exists on disk but
    ``task.yaml`` does not declare ``structural_verifier``. The harness
    will not register the verifier even though the agent can see and
    import it; future analysis tooling that keys off the declaration
    will silently skip the task.
  * ``MISSING_FILE`` — ``task.yaml`` declares ``structural_verifier``
    but the referenced file does not exist. The harness loader treats
    this as a hard error at task-load time; we want CI to surface it
    earlier.

The tool intentionally does NOT enforce that every task ship a
verifier; verifiers are optional by schema.

Exit code:
    0 — no inconsistencies
    1 — at least one inconsistency (each printed to stderr)
    2 — discovery error (e.g. tasks dir missing or unreadable)

Usage:
    python tools/check_structural_verifier_consistency.py
    python tools/check_structural_verifier_consistency.py --root /path/to/onlycodes
    python tools/check_structural_verifier_consistency.py --self-test
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterator, NamedTuple


# Match a top-level ``structural_verifier:`` key. ``task.yaml`` does not
# nest the field, so a simple line-anchored regex is sufficient and
# avoids a yaml dependency for this lightweight CI gate.
_DECL_RE = re.compile(r"^structural_verifier\s*:\s*(\S+)\s*$", re.MULTILINE)


class Violation(NamedTuple):
    task_dir: Path
    kind: str   # "MISSING_DECLARATION" | "MISSING_FILE"
    detail: str

    def format(self, root: Path) -> str:
        rel = self.task_dir.relative_to(root)
        return f"  {rel}: {self.kind}: {self.detail}"


def find_task_yamls(root: Path) -> list[Path]:
    """Return every ``task.yaml`` under ``problems/artifact/``."""
    base = root / "problems" / "artifact"
    if not base.is_dir():
        return []
    return sorted(base.glob("*/*/task.yaml"))


def _declared_path(task_yaml_text: str) -> str | None:
    """Return the relative path declared as ``structural_verifier`` if any."""
    m = _DECL_RE.search(task_yaml_text)
    if not m:
        return None
    return m.group(1)


def scan_task(task_yaml: Path) -> list[Violation]:
    """Return any inconsistencies for one task."""
    task_dir = task_yaml.parent
    text = task_yaml.read_text()
    declared = _declared_path(text)
    # Convention is workspace/verify.py; the field MAY point elsewhere,
    # so we honor whatever path the manifest declares.
    declared_file = (task_dir / declared) if declared else None
    conventional_file = task_dir / "workspace" / "verify.py"

    out: list[Violation] = []

    if declared is None and conventional_file.is_file():
        out.append(Violation(
            task_dir=task_dir,
            kind="MISSING_DECLARATION",
            detail=(
                "workspace/verify.py exists but task.yaml does not declare "
                "structural_verifier: workspace/verify.py"
            ),
        ))
    elif declared is not None and declared_file is not None and not declared_file.is_file():
        out.append(Violation(
            task_dir=task_dir,
            kind="MISSING_FILE",
            detail=(
                f"task.yaml declares structural_verifier: {declared} but the "
                f"file does not exist on disk"
            ),
        ))

    return out


def scan_all(root: Path) -> list[Violation]:
    violations: list[Violation] = []
    for ty in find_task_yamls(root):
        violations.extend(scan_task(ty))
    return violations


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="repo root (default: parent of tools/)",
    )
    p.add_argument(
        "--self-test",
        action="store_true",
        help="run unit tests against handcrafted fixtures",
    )
    args = p.parse_args(argv)

    if args.self_test:
        return _self_test()

    root: Path = args.root
    task_yamls = find_task_yamls(root)
    if not task_yamls:
        print(f"no task.yaml files found under {root}/problems/artifact/",
              file=sys.stderr)
        return 2

    violations = scan_all(root)
    if violations:
        print(
            f"FAIL: {len(violations)} structural_verifier inconsistency(ies) "
            f"in {len({v.task_dir for v in violations})} task(s):",
            file=sys.stderr,
        )
        for v in violations:
            print(v.format(root), file=sys.stderr)
        return 1

    print(f"OK: scanned {len(task_yamls)} task.yaml file(s); no "
          f"structural_verifier inconsistencies")
    return 0


# ────────────────────────────── self-test ─────────────────────────────────


def _make_task(tmp: Path, *, has_verify: bool, declares: bool) -> Path:
    """Build a minimal task tree under tmp and return the task dir."""
    task = tmp / "problems" / "artifact" / "test_fixture" / f"v{int(has_verify)}_d{int(declares)}"
    (task / "workspace").mkdir(parents=True)
    if has_verify:
        (task / "workspace" / "verify.py").write_text("def verify(p): pass\n")
    yaml_lines = [
        "instance_id: test_fixture__sample",
        "category: test_fixture",
        "difficulty: easy",
        "problem_statement: prompt.md",
        "workspace_dir: workspace/",
        "output_artifact: out.txt",
    ]
    if declares:
        yaml_lines.append("structural_verifier: workspace/verify.py")
    yaml_lines.extend([
        "hidden_grader: grader/hidden.py",
        "reference_output: grader/reference_output.txt",
        "execution_budget:",
        "  max_code_runs: 0",
        "  max_wall_seconds: 0",
    ])
    (task / "task.yaml").write_text("\n".join(yaml_lines) + "\n")
    return task


def _self_test() -> int:
    import tempfile

    failed = 0

    with tempfile.TemporaryDirectory(prefix="check_sv_") as raw:
        tmp = Path(raw)

        # Case 1: has verify.py + declared → clean.
        _make_task(tmp, has_verify=True, declares=True)
        # Case 2: no verify.py + not declared → clean.
        _make_task(tmp, has_verify=False, declares=False)
        # Case 3: has verify.py + NOT declared → MISSING_DECLARATION.
        case3 = _make_task(tmp, has_verify=True, declares=False)
        # Case 4: declared + NO verify.py → MISSING_FILE.
        case4 = _make_task(tmp, has_verify=False, declares=True)

        violations = scan_all(tmp)
        kinds = {v.task_dir: v.kind for v in violations}

        if kinds.get(case3) != "MISSING_DECLARATION":
            print(f"FAIL: case3 expected MISSING_DECLARATION, got {kinds.get(case3)}",
                  file=sys.stderr)
            failed += 1
        if kinds.get(case4) != "MISSING_FILE":
            print(f"FAIL: case4 expected MISSING_FILE, got {kinds.get(case4)}",
                  file=sys.stderr)
            failed += 1
        # Cases 1 and 2 must produce no violation rows.
        clean_dirs = {
            tmp / "problems" / "artifact" / "test_fixture" / "v1_d1",
            tmp / "problems" / "artifact" / "test_fixture" / "v0_d0",
        }
        for v in violations:
            if v.task_dir in clean_dirs:
                print(f"FAIL: clean fixture flagged: {v.format(tmp)}",
                      file=sys.stderr)
                failed += 1

        # Also exercise the regex on a yaml that has the field elsewhere
        # (e.g. inside a tag string) — must still match the keyed line.
        weird = (
            "tags: [structural_verifier_unrelated]\n"
            "structural_verifier: workspace/verify.py\n"
        )
        if _declared_path(weird) != "workspace/verify.py":
            print("FAIL: regex did not detect declaration in mixed yaml",
                  file=sys.stderr)
            failed += 1
        # And a yaml where the token only appears in a comment-like line
        # MUST NOT count as a declaration.
        commentish = "tags:\n  - structural_verifier\n"
        if _declared_path(commentish) is not None:
            print("FAIL: regex matched a tag list as a declaration",
                  file=sys.stderr)
            failed += 1

    if failed:
        print(f"\n{failed} self-test failure(s)", file=sys.stderr)
        return 1
    print("OK: self-test passed (4 fixtures + 2 regex cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
