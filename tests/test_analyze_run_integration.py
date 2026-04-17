"""End-to-end integration test for ``swebench analyze pathology``.

Requires a real ``claude`` binary; otherwise skipped cleanly. Runs the
pipeline against the committed fixture, and asserts that at least one
subagent sidecar is produced and parses as JSON.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from swebench.analyze import analyze_command


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "analyze" / "both_arms"


@pytest.mark.integration
@pytest.mark.skipif(
    not shutil.which("claude"),
    reason="integration test requires the claude binary on PATH",
)
def test_pathology_end_to_end(tmp_path: Path) -> None:
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
