"""Tests for the effective-pass test classifier (Issue #273).

Before #273, ``harness.run_tests`` returned PASS purely on ``returncode == 0``.
Both pytest and unittest exit 0 when every collected test is skipped or when
zero tests run, so all-skipped runs were silently scored PASS even though no
test actually exercised the agent's fix.

These tests pin the parser behaviour and the ``run_tests`` downgrade path.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import swebench.harness as _harness_mod
from swebench.harness import _classify_test_result, run_tests


# ---------------------------------------------------------------------------
# _classify_test_result — pytest output shapes
# ---------------------------------------------------------------------------


class TestClassifyPytest:
    def test_pytest_one_passed(self):
        out = (
            "tests/test_x.py .                              [100%]\n"
            "============================== 1 passed in 0.10s ==============================\n"
        )
        ok, reason = _classify_test_result(out)
        assert ok is True
        assert reason is None

    def test_pytest_passed_and_skipped(self):
        out = "===== 3 passed, 2 skipped in 0.42s =====\n"
        ok, reason = _classify_test_result(out)
        assert ok is True

    def test_pytest_only_skipped_is_fail(self):
        out = "============================== 3 skipped in 0.01s ==============================\n"
        ok, reason = _classify_test_result(out)
        assert ok is False
        assert reason is not None and "no passed tests" in reason

    def test_pytest_no_tests_ran_is_fail(self):
        out = "============================== no tests ran in 0.01s ==============================\n"
        ok, reason = _classify_test_result(out)
        assert ok is False
        assert reason is not None and "no tests ran" in reason

    def test_pytest_xpassed_counts_as_executed(self):
        # xpassed = unexpected pass; the test ran and a fix likely made it pass.
        out = "===== 1 xpassed in 0.05s =====\n"
        ok, reason = _classify_test_result(out)
        assert ok is True

    def test_pytest_summary_with_warnings_block_only(self):
        # "5 passed, 1 warning in 0.10s" — warnings are noise; passed counts.
        out = "===== 5 passed, 1 warning in 0.10s =====\n"
        ok, _ = _classify_test_result(out)
        assert ok is True

    def test_pytest_last_summary_wins(self):
        # Pytest invoked twice in one log; trailing summary is authoritative.
        out = (
            "===== 0 passed, 3 skipped in 0.10s =====\n"
            "===== 5 passed in 0.20s =====\n"
        )
        ok, _ = _classify_test_result(out)
        assert ok is True


# ---------------------------------------------------------------------------
# _classify_test_result — unittest / Django runtests.py output shapes
# ---------------------------------------------------------------------------


class TestClassifyUnittest:
    def test_unittest_ok(self):
        out = (
            "....\n"
            "----------------------------------------------------------------------\n"
            "Ran 4 tests in 0.012s\n"
            "\n"
            "OK\n"
        )
        ok, _ = _classify_test_result(out)
        assert ok is True

    def test_unittest_ok_with_partial_skip(self):
        # 4 ran, 1 skipped — still PASS because 3 actually executed.
        out = (
            "Ran 4 tests in 0.012s\n"
            "\n"
            "OK (skipped=1)\n"
        )
        ok, _ = _classify_test_result(out)
        assert ok is True

    def test_unittest_all_skipped_is_fail(self):
        # The django__django-12155 case: 1 ran, 1 skipped → no real test executed.
        out = (
            "s\n"
            "----------------------------------------------------------------------\n"
            "Ran 1 test in 0.000s\n"
            "\n"
            "OK (skipped=1)\n"
        )
        ok, reason = _classify_test_result(out)
        assert ok is False
        assert reason is not None and "skipped all 1" in reason

    def test_unittest_zero_tests_is_fail(self):
        out = (
            "----------------------------------------------------------------------\n"
            "Ran 0 tests in 0.000s\n"
            "\n"
            "OK\n"
        )
        ok, reason = _classify_test_result(out)
        assert ok is False
        assert reason is not None and "0 tests run" in reason

    def test_unittest_ok_with_expected_failures_and_partial_skip(self):
        # skipped<ran → PASS even with expected_failures mixed in.
        out = (
            "Ran 7 tests in 0.05s\n"
            "\n"
            "OK (skipped=2, expected_failures=1)\n"
        )
        ok, _ = _classify_test_result(out)
        assert ok is True


# ---------------------------------------------------------------------------
# _classify_test_result — unknown / non-test output
# ---------------------------------------------------------------------------


class TestClassifyUnknownFormat:
    def test_empty_output(self):
        # Trust returncode=0 when nothing to parse.
        ok, _ = _classify_test_result("")
        assert ok is True

    def test_arbitrary_output_no_unittest_or_pytest_markers(self):
        ok, _ = _classify_test_result("just some script output\nhello world\n")
        assert ok is True

    def test_dummy_pass_stub_used_in_other_tests(self):
        # The pre-existing tests in test_harness_instance_env.py write "PASS\n"
        # to the result file as a stub.  That must keep working unchanged.
        ok, _ = _classify_test_result("PASS\n")
        assert ok is True


# ---------------------------------------------------------------------------
# run_tests downgrade integration
# ---------------------------------------------------------------------------


class TestRunTestsDowngradesAllSkipped:
    """run_tests writes FAIL when subprocess exits 0 but no test actually ran."""

    def _patch_python(self, tmp_path: Path) -> str:
        venv_dir = str(tmp_path / "venv")
        (tmp_path / "venv" / "bin").mkdir(parents=True)
        (tmp_path / "venv" / "bin" / "python").write_text("#!/bin/sh\n")
        return venv_dir

    def test_all_skipped_unittest_downgrades_to_fail(self, monkeypatch, tmp_path: Path):
        def _fake_run(cmd, **kw):
            out = kw["stdout"]
            out.write("s\n")
            out.write("----------------------------------------------------------------------\n")
            out.write("Ran 1 test in 0.000s\n\n")
            out.write("OK (skipped=1)\n")
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(_harness_mod.subprocess, "run", _fake_run)

        result_file = str(tmp_path / "result.txt")
        venv_dir = self._patch_python(tmp_path)

        verdict = run_tests(
            repo_dir=str(tmp_path),
            test_cmd="python -m pytest tests/x.py",
            venv_dir=venv_dir,
            result_file=result_file,
        )
        assert verdict == "FAIL"
        body = Path(result_file).read_text()
        assert "skipped all 1 tests" in body
        assert "Issue #273" in body
        assert body.rstrip().endswith("FAIL")

    def test_zero_tests_pytest_downgrades_to_fail(self, monkeypatch, tmp_path: Path):
        def _fake_run(cmd, **kw):
            kw["stdout"].write("===== no tests ran in 0.01s =====\n")
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(_harness_mod.subprocess, "run", _fake_run)
        result_file = str(tmp_path / "result.txt")
        venv_dir = self._patch_python(tmp_path)

        verdict = run_tests(
            repo_dir=str(tmp_path),
            test_cmd="python -m pytest tests/x.py",
            venv_dir=venv_dir,
            result_file=result_file,
        )
        assert verdict == "FAIL"

    def test_real_pass_still_passes(self, monkeypatch, tmp_path: Path):
        def _fake_run(cmd, **kw):
            kw["stdout"].write("===== 5 passed in 0.10s =====\n")
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(_harness_mod.subprocess, "run", _fake_run)
        result_file = str(tmp_path / "result.txt")
        venv_dir = self._patch_python(tmp_path)

        verdict = run_tests(
            repo_dir=str(tmp_path),
            test_cmd="python -m pytest tests/x.py",
            venv_dir=venv_dir,
            result_file=result_file,
        )
        assert verdict == "PASS"
        # No downgrade note for legitimate passes.
        assert "Issue #273" not in Path(result_file).read_text()

    def test_nonzero_returncode_skips_classifier(self, monkeypatch, tmp_path: Path):
        # rc != 0 → FAIL regardless of stdout shape; no downgrade note appended.
        def _fake_run(cmd, **kw):
            kw["stdout"].write("===== 5 passed in 0.10s =====\n")  # liar
            return SimpleNamespace(returncode=1)

        monkeypatch.setattr(_harness_mod.subprocess, "run", _fake_run)
        result_file = str(tmp_path / "result.txt")
        venv_dir = self._patch_python(tmp_path)

        verdict = run_tests(
            repo_dir=str(tmp_path),
            test_cmd="python -m pytest tests/x.py",
            venv_dir=venv_dir,
            result_file=result_file,
        )
        assert verdict == "FAIL"
        assert "Issue #273" not in Path(result_file).read_text()
