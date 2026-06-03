"""Tests for the pre-flight ``pytest --collect-only`` integration in run.py.

Issue #238 / #234 (and Issue #287).  The pre-flight check must:
  - Run after ``apply_test_patch`` — both now happen *post*-agent (#287).
  - Record ``FAIL`` (not ``env_fail``) and skip ``run_tests`` when zero items
    collect post-agent — the env was proven healthy in setup, so 0 collected
    means the agent broke an import, which counts against pass rate.
  - Mark the run as a "complete" triple for ``--resume`` purposes.
  - Preserve the agent transcript already appended to the .jsonl on collect-fail
    (#287 ordering change): only the meta record on line 1 gets its
    ``verdict`` field updated to ``FAIL``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swebench.models import Problem
from swebench.run import _is_triple_complete


# ---------------------------------------------------------------------------
# _is_triple_complete recognises env_fail
# ---------------------------------------------------------------------------


INSTANCE = "sympy__sympy-14180"
ARM = "baseline"
RUN_IDX = 1


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _paths(tmp_path: Path) -> tuple[Path, Path]:
    jsonl = tmp_path / f"{INSTANCE}_{ARM}_run{RUN_IDX}.jsonl"
    test_txt = tmp_path / f"{INSTANCE}_{ARM}_run{RUN_IDX}_test.txt"
    return jsonl, test_txt


def test_env_fail_verdict_is_treated_as_complete(tmp_path: Path):
    """``env_fail`` in the test file's last non-empty line → triple is complete."""
    jsonl, test_txt = _paths(tmp_path)
    _write(jsonl, '{"type": "meta", "verdict": "env_fail"}\n')
    _write(test_txt, "pre-flight collected 0 items\n\nenv_fail\n")

    assert _is_triple_complete(tmp_path, INSTANCE, ARM, RUN_IDX) == "env_fail"


def test_env_fail_with_trailing_blank_lines(tmp_path: Path):
    """Trailing whitespace after env_fail is still complete."""
    jsonl, test_txt = _paths(tmp_path)
    _write(jsonl, '{"type": "meta"}\n')
    _write(test_txt, "some output\nenv_fail\n\n   \n")

    assert _is_triple_complete(tmp_path, INSTANCE, ARM, RUN_IDX) == "env_fail"


def test_unknown_terminal_token_is_incomplete(tmp_path: Path):
    """Any token other than PASS/FAIL/env_fail → incomplete (must re-run)."""
    jsonl, test_txt = _paths(tmp_path)
    _write(jsonl, '{"type": "meta"}\n')
    _write(test_txt, "stuff\nPENDING\n")

    assert _is_triple_complete(tmp_path, INSTANCE, ARM, RUN_IDX) is None


# ---------------------------------------------------------------------------
# _run_arm short-circuits on pre-flight failure
# ---------------------------------------------------------------------------


def _make_problem(tmp_path: Path) -> Problem:
    """Build a minimal Problem instance for the env_fail flow."""
    return Problem(
        instance_id=INSTANCE,
        repo_slug="sympy/sympy",
        base_commit="abc123",
        test_cmd="python -m pytest test_latex_log",
        problem_statement="dummy",
        patch_file=None,  # avoid file system patch operations
        added_at="2026-01-01",
        hf_split="test",
    )


def test_run_arm_writes_fail_when_preflight_collect_empty(monkeypatch, tmp_path: Path):
    """When post-agent pre-flight reports 0 items, _run_arm must skip ``run_tests``
    and write ``FAIL`` to both the jsonl and the test file.

    Under Issue #287 the agent runs *before* pre-flight, so the agent
    transcript must be preserved in the .jsonl; only the meta record on
    line 1 gets its ``verdict`` field flipped to ``FAIL``.
    """
    from swebench import run as run_mod

    # Pre-flight returns False (0 items collected) post-agent.
    monkeypatch.setattr(
        run_mod,
        "run_preflight_collect",
        lambda **kw: (False, "no tests ran in 0.05s\n"),
    )
    # Resolver passes through unchanged.
    monkeypatch.setattr(
        run_mod,
        "resolve_test_node_ids",
        lambda cmd, **kw: cmd,
    )
    monkeypatch.setattr(run_mod, "git_reset", lambda *a, **kw: None)

    # ``run_tests`` must not be invoked when post-agent preflight fails.
    def _boom_run_tests(**kw):  # pragma: no cover
        raise AssertionError(
            "run_tests must not be invoked when post-agent pre-flight fails"
        )

    monkeypatch.setattr(run_mod, "run_tests", _boom_run_tests)

    # Stub runner that appends a fake transcript line, simulating a real agent.
    class _TranscriptRunner:
        surface = "claude_code"

        def build_tools_flags(self, arm, cfg):
            return []

        def get_version(self, binary):
            return "test"

        def extract_metadata(self, path):
            return (None, None)

        def invoke(self, **kw):
            # Append a fake transcript record after the meta line, so the
            # test can verify it survives the env_fail rewrite.
            with open(kw["result_file"], "a") as out:
                out.write(
                    '{"type":"assistant","content":"thinking"}\n'
                    '{"type":"result","total_cost_usd":0.0,"num_turns":1}\n'
                )

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()
    results_dir = tmp_path / "results"
    results_dir.mkdir()

    problem = _make_problem(tmp_path)

    verdict = run_mod._run_arm(
        problem=problem,
        arm=ARM,
        run_idx=RUN_IDX,
        repo_dir=str(repo_dir),
        venv_dir=str(venv_dir),
        results_dir=str(results_dir),
        agent_binary="/usr/bin/claude",
        mcp_config_path=str(tmp_path / "mcp.json"),
        root=tmp_path,
        runner=_TranscriptRunner(),
    )

    assert verdict == "FAIL"

    test_txt = results_dir / f"{INSTANCE}_{ARM}_run{RUN_IDX}_test.txt"
    assert test_txt.exists()
    # Last non-empty line is FAIL.
    last = [line for line in test_txt.read_text().splitlines() if line.strip()][-1]
    assert last.strip() == "FAIL"

    jsonl = results_dir / f"{INSTANCE}_{ARM}_run{RUN_IDX}.jsonl"
    assert jsonl.exists()
    # Meta record present and carries FAIL verdict (line 1).
    import json
    lines = jsonl.read_text().splitlines()
    first = json.loads(lines[0])
    assert first["verdict"] == "FAIL"
    assert first["instance_id"] == INSTANCE
    # Agent transcript still present after the meta line (#287 invariant).
    assert any("assistant" in ln or "result" in ln for ln in lines[1:]), (
        f"Agent transcript was wiped on env_fail; lines: {lines}"
    )


def test_run_arm_proceeds_when_preflight_passes(monkeypatch, tmp_path: Path):
    """Pre-flight True must NOT short-circuit; downstream agent is invoked."""
    from swebench import run as run_mod

    monkeypatch.setattr(
        run_mod,
        "run_preflight_collect",
        lambda **kw: (True, ""),
    )
    monkeypatch.setattr(
        run_mod,
        "resolve_test_node_ids",
        lambda cmd, **kw: cmd,
    )
    monkeypatch.setattr(run_mod, "git_reset", lambda *a, **kw: None)

    invoked = {"count": 0}

    class _StubRunner:
        surface = "claude_code"

        def build_tools_flags(self, arm, cfg):
            return []

        def get_version(self, binary):
            return "test"

        def extract_metadata(self, path):
            return (None, None)

        def invoke(self, **kw):
            invoked["count"] += 1
            # Touch the result file so downstream code does not blow up on
            # missing-file reads.
            Path(kw["result_file"]).write_text(
                '{"type": "result", "total_cost_usd": 0.0, "num_turns": 0}\n'
            )

    def _stub_run_tests(**kw):
        Path(kw["result_file"]).write_text("PASS\n")
        return "PASS"

    monkeypatch.setattr(run_mod, "run_tests", _stub_run_tests)

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()
    results_dir = tmp_path / "results"
    results_dir.mkdir()

    problem = _make_problem(tmp_path)

    verdict = run_mod._run_arm(
        problem=problem,
        arm=ARM,
        run_idx=RUN_IDX,
        repo_dir=str(repo_dir),
        venv_dir=str(venv_dir),
        results_dir=str(results_dir),
        agent_binary="/usr/bin/claude",
        mcp_config_path=str(tmp_path / "mcp.json"),
        root=tmp_path,
        runner=_StubRunner(),
    )

    assert verdict == "PASS"
    assert invoked["count"] == 1
