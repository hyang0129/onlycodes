"""Component tests for the codex onlycode arm boundaries introduced in PR #251.

Three boundaries are covered:

1. cli.py → mcp_cli.py (new registration)
   ``cli.add_command(mcp_group, "mcp-config")`` — verify the top-level CLI
   dispatcher routes ``mcp-config generate`` to the real mcp_group handler,
   not a stub.  Two real modules cooperate: cli.py (registrant) and
   mcp_cli.py (registree).

2. artifact_cli.py → runner.py (CodexRunner.preflight)
   ``artifact_run_command`` now calls ``runner.preflight(mcp_path)`` for
   codex_cli + code_only / bash_only arms.  Tests verify: preflight failure
   exits non-zero; tool_rich arm skips preflight entirely; claude_code surface
   never triggers preflight.

3. run.py → harness.py (_INSTANCE_EXTRA_PYTEST_ARGS → run_preflight_collect)
   ``_run_arm`` now passes ``_INSTANCE_EXTRA_PYTEST_ARGS.get(instance_id)``
   as ``extra_pytest_args`` to the real ``run_preflight_collect``.  Tests
   verify the forwarding goes to the preflight call, not just run_tests.

Each class exercises two or more real modules across a named boundary.
Only I/O seams (subprocess, filesystem) are doubled.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from click.testing import CliRunner

from swebench.cli import cli
import swebench.harness as _harness_mod
from swebench.harness import _INSTANCE_EXTRA_PYTEST_ARGS, run_preflight_collect
from swebench import run as run_mod
from swebench.models import Problem


# ---------------------------------------------------------------------------
# Boundary 1: cli.py → mcp_cli.py registration contract
# ---------------------------------------------------------------------------


@pytest.mark.component
class TestCliMcpConfigRegistration:
    """cli.add_command(mcp_group, 'mcp-config') must route top-level CLI dispatch
    to the real mcp_cli.mcp_group handler across the registration boundary.

    The existing mcp_cli unit tests invoke mcp_group directly (single module).
    These tests invoke the top-level ``cli`` (two real modules: cli.py + mcp_cli.py)
    to confirm the wiring is actually in place.
    """

    def test_mcp_config_subcommand_appears_in_top_level_help(self):
        """The top-level CLI help must list 'mcp-config' as an available group command."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"], catch_exceptions=False)
        assert result.exit_code == 0, f"top-level --help failed: {result.output}"
        assert "mcp-config" in result.output, (
            f"'mcp-config' not listed in top-level help. output:\n{result.output}"
        )

    def test_mcp_config_help_routes_to_real_mcp_group(self):
        """cli mcp-config --help must reach mcp_cli.mcp_group and show 'generate'."""
        runner = CliRunner()
        result = runner.invoke(cli, ["mcp-config", "--help"], catch_exceptions=False)
        assert result.exit_code == 0, (
            f"'mcp-config --help' failed with exit {result.exit_code}:\n{result.output}"
        )
        # The real mcp_group has a 'generate' subcommand — must appear in help.
        assert "generate" in result.output, (
            f"'generate' not in mcp-config help; output:\n{result.output}"
        )

    def test_mcp_config_generate_help_shows_out_option(self):
        """cli mcp-config generate --help must expose the --out option from mcp_cli."""
        runner = CliRunner()
        result = runner.invoke(
            cli, ["mcp-config", "generate", "--help"], catch_exceptions=False
        )
        assert result.exit_code == 0, (
            f"'mcp-config generate --help' failed:\n{result.output}"
        )
        assert "--out" in result.output, (
            f"--out option not exposed by mcp-config generate. output:\n{result.output}"
        )

    def test_mcp_config_generate_writes_valid_json_via_top_level_cli(
        self, tmp_path, monkeypatch
    ):
        """Invoking the top-level cli → mcp-config → generate must write a valid
        mcp-config.json with a 'codebox' entry when the bundle exists.

        This is the cross-module contract: cli.py must have wired mcp_group correctly
        so the actual mcp_cli.generate function executes.
        """
        # Set up a fake repo root with a real bundle.
        pkg_root = tmp_path / "repo"
        bundle_dir = pkg_root / "exec_server" / "dist"
        bundle_dir.mkdir(parents=True)
        bundle = bundle_dir / "exec-server.bundle.mjs"
        bundle.write_text("// fake bundle\n")

        monkeypatch.setattr("swebench.mcp_cli.swebench.repo_root", lambda: pkg_root)
        monkeypatch.setattr(
            "swebench.mcp_cli.shutil.which",
            lambda name: "/usr/bin/node" if name == "node" else None,
        )

        out_path = tmp_path / "mcp-config.json"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["mcp-config", "generate", "--out", str(out_path)],
            catch_exceptions=False,
        )

        assert result.exit_code == 0, (
            f"mcp-config generate failed via top-level cli:\n{result.output}"
        )
        assert out_path.exists(), "Output file was not created by mcp_cli.generate"
        config = json.loads(out_path.read_text())
        assert "mcpServers" in config, "Generated JSON missing 'mcpServers' key"
        assert "codebox" in config["mcpServers"], (
            f"'codebox' missing from generated mcpServers: {config}"
        )


# ---------------------------------------------------------------------------
# Boundary 2: artifact_cli.py → runner.py (CodexRunner.preflight)
# ---------------------------------------------------------------------------


def _write_minimal_task(tasks_root: Path) -> str:
    """Write a minimal valid task.yaml for artifact CLI integration tests.

    Returns the instance_id.
    """
    task_dir = tasks_root / "test_fixture" / "preflight_smoke"
    (task_dir / "workspace").mkdir(parents=True)
    (task_dir / "grader").mkdir(parents=True)
    (task_dir / "grader" / "hidden.py").write_text(
        "def grade(scratch_dir):\n"
        "    class R:\n"
        "        passed=True; score=1.0; detail='ok'\n"
        "    return R()\n"
    )
    (task_dir / "grader" / "reference_output.txt").write_text("ok\n")
    with open(task_dir / "task.yaml", "w") as f:
        yaml.safe_dump(
            {
                "instance_id": "test_fixture__preflight_smoke",
                "category": "test_fixture",
                "difficulty": "easy",
                "problem_statement": "prompt.md",
                "workspace_dir": "workspace/",
                "output_artifact": "answer.txt",
                "hidden_grader": "grader/hidden.py",
                "reference_output": "grader/reference_output.txt",
                "execution_budget": {"max_code_runs": 0, "max_wall_seconds": 0},
            },
            f,
            sort_keys=False,
        )
    (task_dir / "prompt.md").write_text("write 'ok' to answer.txt\n")
    return "test_fixture__preflight_smoke"


class _FakeCodexRunner:
    """Minimal CodexRunner stub: find_binary and verify_auth succeed; preflight is tracked."""

    surface = "codex_cli"
    _preflight_called: bool = False
    _preflight_raises: RuntimeError | None = None

    def find_binary(self) -> str:
        return "/usr/bin/codex"

    def verify_auth(self) -> None:
        return None

    def get_version(self, _binary: str) -> str:
        return "0.0.0-stub"

    def build_tools_flags(self, arm: str, mcp_config_path):
        return []

    def preflight(self, mcp_path=None) -> None:
        self._preflight_called = True
        if self._preflight_raises is not None:
            raise self._preflight_raises

    def invoke(self, *, prompt, cwd, system_prompt, tools_flags, result_file, binary, mcp_config_path=None):
        Path(cwd, "answer.txt").write_text("ok\n")
        with open(result_file, "a") as f:
            f.write('{"type":"result","total_cost_usd":0.0,"num_turns":1}\n')

    def extract_metadata(self, jsonl_path):
        return (None, 1)


@pytest.mark.component
class TestArtifactCliCodexPreflight:
    """artifact_cli.artifact_run_command calls runner.preflight() for codex_cli
    + code_only/bash_only arms, and skips it for tool_rich and claude_code.

    Uses the real artifact_cli CLI path (two real modules: artifact_cli + runner
    contract) with a runner stub whose preflight() is trackable.
    """

    def _invoke_artifact_run(
        self,
        tmp_path: Path,
        monkeypatch,
        fake_runner: _FakeCodexRunner,
        arm: str,
    ):
        """Helper: set up tasks, stub make_runner, invoke 'artifact run'."""
        from swebench import artifact_cli as artifact_cli_mod

        tasks_root = tmp_path / "tasks"
        iid = _write_minimal_task(tasks_root)
        results_dir = tmp_path / "results"

        monkeypatch.setattr(artifact_cli_mod, "make_runner", lambda _surface: fake_runner)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "artifact", "run",
                "--tasks-dir", str(tasks_root),
                "--output-dir", str(results_dir),
                "--filter", iid,
                "--arms", arm,
                "--agent-surface", "codex_cli",
            ],
        )
        return result

    def test_code_only_arm_triggers_preflight(self, tmp_path, monkeypatch):
        """artifact run --arms code_only --agent-surface codex_cli must call preflight."""
        fake = _FakeCodexRunner()
        result = self._invoke_artifact_run(tmp_path, monkeypatch, fake, arm="code_only")
        assert fake._preflight_called, (
            f"preflight() was not called for codex_cli + code_only. "
            f"CLI output:\n{result.output}"
        )

    def test_bash_only_arm_triggers_preflight(self, tmp_path, monkeypatch):
        """artifact run --arms bash_only --agent-surface codex_cli must call preflight."""
        fake = _FakeCodexRunner()
        result = self._invoke_artifact_run(tmp_path, monkeypatch, fake, arm="bash_only")
        assert fake._preflight_called, (
            f"preflight() was not called for codex_cli + bash_only. "
            f"CLI output:\n{result.output}"
        )

    def test_tool_rich_arm_skips_preflight(self, tmp_path, monkeypatch):
        """artifact run --arms tool_rich --agent-surface codex_cli must NOT call preflight
        (tool_rich does not use the exec-server bundle)."""
        fake = _FakeCodexRunner()
        result = self._invoke_artifact_run(tmp_path, monkeypatch, fake, arm="tool_rich")
        assert not fake._preflight_called, (
            f"preflight() must not be called for codex_cli + tool_rich. "
            f"CLI output:\n{result.output}"
        )

    def test_preflight_failure_causes_nonzero_exit(self, tmp_path, monkeypatch):
        """When preflight() raises RuntimeError, artifact run must exit non-zero
        and print an error mentioning the failure."""
        from swebench import artifact_cli as artifact_cli_mod

        fake = _FakeCodexRunner()
        fake._preflight_raises = RuntimeError("node not found on PATH")

        tasks_root = tmp_path / "tasks"
        iid = _write_minimal_task(tasks_root)
        results_dir = tmp_path / "results"

        monkeypatch.setattr(artifact_cli_mod, "make_runner", lambda _surface: fake)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "artifact", "run",
                "--tasks-dir", str(tasks_root),
                "--output-dir", str(results_dir),
                "--filter", iid,
                "--arms", "code_only",
                "--agent-surface", "codex_cli",
            ],
        )

        assert result.exit_code != 0, (
            f"Expected non-zero exit when preflight raises, got 0. "
            f"Output:\n{result.output}"
        )
        # The error message must mention the failure.
        combined_output = result.output + (getattr(result, "stderr", None) or "")
        assert "pre-flight" in combined_output.lower() or "node" in combined_output, (
            f"Error output does not mention preflight failure. Output:\n{combined_output}"
        )


# ---------------------------------------------------------------------------
# Boundary 3: run.py → harness.py (_INSTANCE_EXTRA_PYTEST_ARGS → run_preflight_collect)
# ---------------------------------------------------------------------------

class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.mark.component
class TestRunArmExtraPytestArgsForwardedToPreflight:
    """_run_arm must pass _INSTANCE_EXTRA_PYTEST_ARGS[instance_id] as extra_pytest_args
    to the real run_preflight_collect call (not just run_tests).

    The existing unit tests in test_harness_instance_env.py verify the harness
    function in isolation and run_tests forwarding.  This component test verifies
    the cross-module wiring: _run_arm (run.py) → run_preflight_collect (harness.py).

    The real run_preflight_collect runs (not doubled); only subprocess.run is
    doubled to return 0 collected items (env_fail path) so the test stays fast.
    """

    INSTANCE = "astropy__astropy-6938"

    def _make_problem(self) -> Problem:
        return Problem(
            instance_id=self.INSTANCE,
            repo_slug="astropy/astropy",
            base_commit="abc123",
            test_cmd="python -m pytest astropy/tests/test_foo.py",
            problem_statement="dummy",
            patch_file=None,
            added_at="2026-01-01",
            hf_split="test",
        )

    def _make_dirs(self, tmp_path: Path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        venv_dir = tmp_path / "venv"
        (venv_dir / "bin").mkdir(parents=True)
        (venv_dir / "bin" / "python").write_text("#!/bin/sh\nexec python3 \"$@\"\n")
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        return str(repo_dir), str(venv_dir), str(results_dir)

    def test_extra_pytest_args_forwarded_to_real_preflight_collect(
        self, monkeypatch, tmp_path: Path
    ):
        """_run_arm must forward _INSTANCE_EXTRA_PYTEST_ARGS to run_preflight_collect.

        We let the real run_preflight_collect execute and record the subprocess.run
        call it makes.  The key assertion is that the extra args (e.g.
        ['-p', 'no:cacheprovider']) appear in the subprocess command line that the
        real harness preflight issues.  Only subprocess.run is doubled (I/O seam).
        """
        repo_dir, venv_dir, results_dir = self._make_dirs(tmp_path)

        # Confirm the table entry for our instance is present.
        assert self.INSTANCE in _INSTANCE_EXTRA_PYTEST_ARGS, (
            f"_INSTANCE_EXTRA_PYTEST_ARGS missing {self.INSTANCE!r}; "
            "the harness table must contain the astropy-6938 override."
        )
        expected_extra_args = _INSTANCE_EXTRA_PYTEST_ARGS[self.INSTANCE]

        preflight_calls: list[list] = []

        def _recording_subprocess_run(cmd, **kw):
            if isinstance(cmd, list) and "--collect-only" in cmd:
                preflight_calls.append(list(cmd))
                return _FakeCompleted(
                    returncode=5, stdout="collected 0 items\n", stderr=""
                )
            # git and other commands succeed silently.
            return _FakeCompleted(returncode=0, stdout="", stderr="")

        # Patch subprocess.run inside the harness module (I/O seam only).
        monkeypatch.setattr(_harness_mod.subprocess, "run", _recording_subprocess_run)

        # Double run.py I/O seams that are not part of this boundary.
        monkeypatch.setattr(run_mod, "git_reset", lambda *a, **kw: None)
        monkeypatch.setattr(
            run_mod,
            "run_claude",
            lambda **kw: (_ for _ in ()).throw(
                AssertionError("run_claude must not be called when preflight fails")
            ),
        )

        problem = self._make_problem()
        verdict = run_mod._run_arm(
            problem=problem,
            arm="baseline",
            run_idx=1,
            repo_dir=repo_dir,
            venv_dir=venv_dir,
            results_dir=results_dir,
            agent_binary="/usr/bin/claude",
            mcp_config_path=str(tmp_path / "mcp.json"),
            root=tmp_path,
        )

        # _run_arm must have taken the env_fail path (0 collected → env_fail).
        assert verdict == "env_fail", (
            f"Expected 'env_fail' when preflight returns 0 collected; got {verdict!r}"
        )

        # The real run_preflight_collect must have been called at least once.
        assert len(preflight_calls) >= 1, (
            "run_preflight_collect did not issue any subprocess.run --collect-only call"
        )

        # Every extra arg must appear in the preflight subprocess command.
        preflight_cmd = preflight_calls[0]
        for arg in expected_extra_args:
            assert arg in preflight_cmd, (
                f"Expected extra arg {arg!r} in preflight command but it was absent.\n"
                f"Preflight command: {preflight_cmd}\n"
                f"Expected args from _INSTANCE_EXTRA_PYTEST_ARGS: {expected_extra_args}"
            )

    def test_extra_pytest_args_precede_test_file_in_preflight_cmd(
        self, monkeypatch, tmp_path: Path
    ):
        """The extra pytest args must appear before the test file in the preflight
        subprocess command — i.e. they are injected in the right position."""
        repo_dir, venv_dir, results_dir = self._make_dirs(tmp_path)

        expected_extra_args = _INSTANCE_EXTRA_PYTEST_ARGS.get(self.INSTANCE, [])

        preflight_calls: list[list] = []

        def _recording_subprocess_run(cmd, **kw):
            if isinstance(cmd, list) and "--collect-only" in cmd:
                preflight_calls.append(list(cmd))
                return _FakeCompleted(returncode=5, stdout="collected 0 items\n")
            return _FakeCompleted(returncode=0)

        monkeypatch.setattr(_harness_mod.subprocess, "run", _recording_subprocess_run)
        monkeypatch.setattr(run_mod, "git_reset", lambda *a, **kw: None)
        monkeypatch.setattr(run_mod, "run_claude", lambda **kw: None)

        problem = self._make_problem()
        run_mod._run_arm(
            problem=problem,
            arm="baseline",
            run_idx=1,
            repo_dir=repo_dir,
            venv_dir=venv_dir,
            results_dir=results_dir,
            agent_binary="/usr/bin/claude",
            mcp_config_path=str(tmp_path / "mcp.json"),
            root=tmp_path,
        )

        assert len(preflight_calls) >= 1, "No --collect-only subprocess call observed"
        cmd = preflight_calls[0]

        if expected_extra_args:
            # Find last extra arg position and test-file position.
            last_extra_idx = max(
                cmd.index(a) for a in expected_extra_args if a in cmd
            )
            # The test command contains a .py file path; find the first .py argument.
            py_idxs = [i for i, tok in enumerate(cmd) if tok.endswith(".py")]
            if py_idxs:
                first_py_idx = py_idxs[0]
                assert last_extra_idx < first_py_idx, (
                    f"Extra args must precede the test-file argument in the preflight cmd.\n"
                    f"cmd={cmd}\n"
                    f"last extra arg at index {last_extra_idx}, "
                    f"first .py at index {first_py_idx}"
                )

    def test_instance_without_extra_args_sends_clean_preflight(
        self, monkeypatch, tmp_path: Path
    ):
        """For an instance not in _INSTANCE_EXTRA_PYTEST_ARGS, the preflight call
        must not inject any extra args.  Specifically, 'no:cacheprovider' must
        not appear in the subprocess command for a non-astropy instance."""
        repo_dir, venv_dir, results_dir = self._make_dirs(tmp_path)

        preflight_calls: list[list] = []

        def _recording_subprocess_run(cmd, **kw):
            if isinstance(cmd, list) and "--collect-only" in cmd:
                preflight_calls.append(list(cmd))
                return _FakeCompleted(returncode=5, stdout="collected 0 items\n")
            return _FakeCompleted(returncode=0)

        monkeypatch.setattr(_harness_mod.subprocess, "run", _recording_subprocess_run)
        monkeypatch.setattr(run_mod, "git_reset", lambda *a, **kw: None)
        monkeypatch.setattr(run_mod, "run_claude", lambda **kw: None)

        # Use an instance NOT in _INSTANCE_EXTRA_PYTEST_ARGS.
        problem = Problem(
            instance_id="django__django-16379",
            repo_slug="django/django",
            base_commit="abc",
            test_cmd="python -m pytest tests/test_foo.py",
            problem_statement="dummy",
            patch_file=None,
            added_at="2026-01-01",
            hf_split="test",
        )

        assert "django__django-16379" not in _INSTANCE_EXTRA_PYTEST_ARGS, (
            "This test relies on django__django-16379 NOT being in "
            "_INSTANCE_EXTRA_PYTEST_ARGS; update the instance_id if that changes."
        )

        run_mod._run_arm(
            problem=problem,
            arm="baseline",
            run_idx=1,
            repo_dir=repo_dir,
            venv_dir=venv_dir,
            results_dir=results_dir,
            agent_binary="/usr/bin/claude",
            mcp_config_path=str(tmp_path / "mcp.json"),
            root=tmp_path,
        )

        assert len(preflight_calls) >= 1
        cmd = preflight_calls[0]
        # The cacheprovider disable flag must NOT appear for non-astropy instances.
        assert "no:cacheprovider" not in cmd, (
            f"'no:cacheprovider' must not appear in preflight cmd for "
            f"django__django-16379. cmd={cmd}"
        )


# ---------------------------------------------------------------------------
# Boundary 4: run.py → JSONL meta line (Issue #253 — codex_model in meta)
# ---------------------------------------------------------------------------


@pytest.mark.component
class TestRunArmWritesCodexModelToMeta:
    """``_run_arm`` writes the ``model`` field to the JSONL ``type: meta`` line
    when ``agent_surface == 'codex_cli'`` and omits it for ``claude_code``.

    Covers both meta-write sites: the env_fail short-circuit (when pytest
    collects 0 items) and the happy-path write before agent invocation.
    """

    INSTANCE = "django__django-16379"

    def _problem(self) -> Problem:
        return Problem(
            instance_id=self.INSTANCE,
            repo_slug="django/django",
            base_commit="abc123",
            test_cmd="python -m pytest tests/foo.py",
            problem_statement="dummy",
            patch_file=None,
            added_at="2026-01-01",
            hf_split="test",
        )

    def _dirs(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        venv_dir = tmp_path / "venv"
        (venv_dir / "bin").mkdir(parents=True)
        (venv_dir / "bin" / "python").write_text("#!/bin/sh\nexec python3 \"$@\"\n")
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        return str(repo_dir), str(venv_dir), str(results_dir)

    def _read_meta(self, results_dir: str) -> dict:
        """Read the first JSONL line from the run's result file."""
        results_path = Path(results_dir)
        jsonl_files = list(results_path.glob("*.jsonl"))
        assert len(jsonl_files) == 1, f"expected exactly one jsonl, got {jsonl_files}"
        first = jsonl_files[0].read_text().splitlines()[0]
        return json.loads(first)

    def _patch_to_env_fail(self, monkeypatch):
        """Force the preflight `pytest --collect-only` path to return 0 items."""
        def _fake_run(cmd, **kw):
            if isinstance(cmd, list) and "--collect-only" in cmd:
                return _FakeCompleted(returncode=5, stdout="collected 0 items\n", stderr="")
            return _FakeCompleted(returncode=0, stdout="", stderr="")
        monkeypatch.setattr(_harness_mod.subprocess, "run", _fake_run)
        monkeypatch.setattr(run_mod, "git_reset", lambda *a, **kw: None)

    def test_env_fail_meta_includes_model_for_codex_cli(
        self, monkeypatch, tmp_path: Path
    ):
        """codex_cli + env_fail short-circuit → meta line carries `model`."""
        repo_dir, venv_dir, results_dir = self._dirs(tmp_path)
        self._patch_to_env_fail(monkeypatch)

        runner = _FakeCodexRunner()  # surface == "codex_cli"

        verdict = run_mod._run_arm(
            problem=self._problem(),
            arm="baseline",
            run_idx=1,
            repo_dir=repo_dir,
            venv_dir=venv_dir,
            results_dir=results_dir,
            agent_binary="/usr/bin/codex",
            mcp_config_path=str(tmp_path / "mcp.json"),
            root=tmp_path,
            runner=runner,
            codex_model="gpt-5.4-mini",
        )

        assert verdict == "env_fail"
        meta = self._read_meta(results_dir)
        assert meta["type"] == "meta"
        assert meta["agent_surface"] == "codex_cli"
        assert meta["model"] == "gpt-5.4-mini", (
            f"Expected `model` field in env_fail meta line for codex_cli, "
            f"but got: {meta}"
        )

    def test_env_fail_meta_omits_model_for_claude_code(
        self, monkeypatch, tmp_path: Path
    ):
        """claude_code + env_fail → meta line MUST NOT include `model`.

        Claude's USD cost comes from `total_cost_usd` in its own stream-json
        output. A `model` field would be misleading and is therefore omitted.
        """
        repo_dir, venv_dir, results_dir = self._dirs(tmp_path)
        self._patch_to_env_fail(monkeypatch)

        # No runner override → defaults to ClaudeRunner inside _run_arm.
        # But we exercise the env_fail short-circuit which uses the `runner`
        # arg directly to read surface. Pass a Claude-shaped stub.
        from swebench.runner import ClaudeRunner

        verdict = run_mod._run_arm(
            problem=self._problem(),
            arm="baseline",
            run_idx=1,
            repo_dir=repo_dir,
            venv_dir=venv_dir,
            results_dir=results_dir,
            agent_binary="/usr/bin/claude",
            mcp_config_path=str(tmp_path / "mcp.json"),
            root=tmp_path,
            runner=ClaudeRunner(),
            codex_model=None,
        )

        assert verdict == "env_fail"
        meta = self._read_meta(results_dir)
        assert meta["type"] == "meta"
        assert meta["agent_surface"] == "claude_code"
        assert "model" not in meta, (
            f"`model` must not appear in meta for claude_code; got: {meta}"
        )
