"""End-to-end integration test for ``swebench analyze pathology``.

Two flavours:

- ``test_pathology_end_to_end_subagents`` — requires a real ``claude``
  binary; runs stages 1 + 2 against the committed fixture and asserts
  at least one subagent sidecar parses as JSON.
- ``test_pathology_full_pipeline_dry_run`` — offline dry-run over all
  three stages, asserting the synthesizer command appears in output
  and the registry file at the repo root is not touched.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from swebench import repo_root
from swebench.analyze import analyze_command


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "analyze" / "both_arms"


@pytest.mark.integration
@pytest.mark.skipif(
    not shutil.which("claude"),
    reason="integration test requires the claude binary on PATH",
)
def test_pathology_end_to_end_subagents(tmp_path: Path) -> None:
    work = tmp_path / "results"
    work.mkdir()
    for p in FIXTURES_DIR.glob("*.jsonl"):
        (work / p.name).write_text(p.read_text())

    runner = CliRunner()
    result = runner.invoke(
        analyze_command,
        [
            "pathology",
            "--results-dir", str(work),
            "--stage", "subagents",
            "--concurrency", "2",
            "--run-id", "itest",
        ],
        catch_exceptions=False,
    )
    # Subagents may error, but the pipeline must not crash outright.
    assert result.exit_code in (0, 1), result.output

    sub_dir = work / "_analysis" / "itest" / "subagents"
    assert sub_dir.exists(), "subagents output directory missing"
    sidecars = list(sub_dir.glob("*.json"))
    assert sidecars, "no subagent sidecars were produced"

    # At least one sidecar should parse as JSON (the subagent prompt demands JSON).
    parsed_any = False
    for sc in sidecars:
        try:
            json.loads(sc.read_text())
            parsed_any = True
            break
        except json.JSONDecodeError:
            continue
    assert parsed_any, "no subagent sidecar parsed as JSON"


def test_pathology_full_pipeline_dry_run(tmp_path: Path) -> None:
    """All three stages run end-to-end under ``--dry-run``, offline.

    - Stage 1 mechanical (dry-run computes metrics in memory).
    - Stage 2 subagents (dry-run prints composed claude commands).
    - Stage 3 synthesizer (dry-run prints composed claude command,
      does NOT touch patterns.json).

    The autouse ``_patterns_json_is_immutable`` fixture in conftest.py
    enforces that the repo-root patterns.json is unchanged after this
    test completes.
    """
    work = tmp_path / "results"
    work.mkdir()
    for p in FIXTURES_DIR.glob("*.jsonl"):
        (work / p.name).write_text(p.read_text())

    runner = CliRunner()
    result = runner.invoke(
        analyze_command,
        [
            "pathology",
            "--results-dir", str(work),
            "--dry-run",
            "--run-id", "itest-dry",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    # Each stage announces itself via a dedicated token in stdout.
    out = result.output
    assert "would extract" in out, "stage 1 dry-run banner missing"
    assert "DRY RUN:" in out, "stage 2 dry-run banner missing"
    assert "stage3 synthesizer" in out, "stage 3 dry-run banner missing"
    # Dry-run must not have written anything under _analysis/.
    assert not (work / "_analysis" / "itest-dry").exists()
    # And it must not have touched the repo-root registry.
    root_patterns = repo_root() / "patterns.json"
    assert root_patterns.exists(), "seed patterns.json missing from repo root"
