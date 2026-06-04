"""Unit tests for the WS-A.2 (#308) Verified materialization tooling:
``scripts/list_verified_ids.py`` and ``scripts/validate_verified_setup.py``.

Hermetic: no network, no real repos, no venv builds. The HuggingFace fetch and
the per-instance cache/collect worker are the only non-hermetic parts and are
exercised only through their pure helpers (rendering, classification, filter
resolution, reporting).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import list_verified_ids as lvi  # noqa: E402
import validate_verified_setup as vvs  # noqa: E402

from swebench.add import _iter_ids_file  # noqa: E402


# --------------------------------------------------------------------------
# list_verified_ids.render
# --------------------------------------------------------------------------

def test_render_roundtrips_through_add_id_parser(tmp_path: Path) -> None:
    """The frozen file's comment header must be ignored and ids preserved in
    order by the same parser `swebench add --from-file` uses."""
    ids = ["django__django-10097", "sympy__sympy-11618", "psf__requests-1142"]
    out = tmp_path / "verified-spine.txt"
    out.write_text(lvi.render(ids))

    parsed = _iter_ids_file(out)
    assert parsed == ids  # order preserved, header + blank lines dropped


def test_render_header_records_count() -> None:
    text = lvi.render(["a__a-1", "b__b-2"])
    assert text.startswith("#")
    assert "Count: 2" in text
    # every non-comment line is an id
    non_comment = [l for l in text.splitlines() if l and not l.startswith("#")]
    assert non_comment == ["a__a-1", "b__b-2"]


# --------------------------------------------------------------------------
# validate_verified_setup.classify
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "blob, expected_class",
    [
        ("ModuleNotFoundError: No module named 'distutils'", "distutils_removed_3_12"),
        ("from collections import Mapping", "collections_abc_removed_3_10"),
        ("Could not find a version that satisfies the requirement foo==1.0",
         "pip_resolver_failure"),
        ("ImportError while importing test module 'tests/test_x.py'.",
         "test_collection_import_error"),
        ("ModuleNotFoundError: No module named 'pytest_asyncio'", "module_not_found"),
        ("ValueError: No closing quotation", "malformed_test_cmd"),
        ("everything was perfectly fine", None),
    ],
)
def test_classify(blob: str, expected_class: str | None) -> None:
    result = vvs.classify(blob)
    if expected_class is None:
        assert result is None
    else:
        assert result is not None and result[0] == expected_class


def test_classify_specific_beats_generic() -> None:
    """distutils removal is a more specific signal than the generic
    module_not_found pattern, and must win (first-match ordering)."""
    blob = "ModuleNotFoundError: No module named 'distutils'"
    assert vvs.classify(blob)[0] == "distutils_removed_3_12"


# --------------------------------------------------------------------------
# validate_verified_setup._resolve_filter
# --------------------------------------------------------------------------

def test_resolve_filter_none() -> None:
    assert vvs._resolve_filter(None) is None
    assert vvs._resolve_filter("") is None


def test_resolve_filter_comma_list() -> None:
    assert vvs._resolve_filter("a, b ,c") == {"a", "b", "c"}


def test_resolve_filter_at_file(tmp_path: Path) -> None:
    f = tmp_path / "ids.txt"
    f.write_text("# header\n\nfoo__bar-1  # inline comment\nfoo__bar-2\n")
    assert vvs._resolve_filter(f"@{f}") == {"foo__bar-1", "foo__bar-2"}


def test_resolve_filter_missing_file_exits(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        vvs._resolve_filter(f"@{tmp_path / 'nope.txt'}")


# --------------------------------------------------------------------------
# reporting: write_buildable + write_summary
# --------------------------------------------------------------------------

def _results() -> list[dict]:
    """A fabricated mixed-status result set."""
    base = dict(returncode=0, timed_out=False, reason=None, build_msg="built",
                lockfile=True, collect_skipped=False, failure_class=None,
                fix_hint=None, log_file="logs/x.log", started_utc="t", finished_utc="t")
    return [
        {**base, "instance_id": "ok__pytest-1", "status": "ok"},
        {**base, "instance_id": "ok__django-2", "status": "ok", "collect_skipped": True},
        {**base, "instance_id": "bad__build-3", "status": "build_fail",
         "failure_class": "distutils_removed_3_12",
         "fix_hint": "pin python", "reason": "CalledProcessError: ..."},
        {**base, "instance_id": "bad__collect-4", "status": "collect_fail",
         "reason": "0 items collected"},
    ]


def test_write_buildable_only_ok_ids(tmp_path: Path) -> None:
    target = tmp_path / "buildable.txt"
    vvs.write_buildable(_results(), [target])
    lines = target.read_text().split()
    # Both ok instances included (collect_skipped is still buildable); failures excluded.
    assert lines == ["ok__django-2", "ok__pytest-1"]  # sorted


def test_write_buildable_writes_multiple_targets(tmp_path: Path) -> None:
    t1, t2 = tmp_path / "a.txt", tmp_path / "nested" / "b.txt"
    vvs.write_buildable(_results(), [t1, t2])
    assert t1.read_text() == t2.read_text()
    assert "ok__pytest-1" in t1.read_text()


def test_write_summary_reports_shortfall(tmp_path: Path) -> None:
    import datetime as dt
    out = tmp_path / "summary.md"
    vvs.write_summary(_results(), out, set_name="swe/swebench-verified",
                      start=dt.datetime(2026, 6, 3, tzinfo=dt.timezone.utc),
                      pool_size=10)
    text = out.read_text()
    # pool 10, buildable 2 -> shortfall 8, reported loudly.
    assert "Shortfall (pool − buildable): 8" in text
    assert "Buildable (built + collected cleanly): **2**" in text
    # failure grouping surfaces the build class + hint.
    assert "distutils_removed_3_12" in text and "pin python" in text


def test_results_json_is_valid(tmp_path: Path) -> None:
    """Sanity: the record shape we write is JSON-serializable as-is."""
    json.dumps(_results())


# --------------------------------------------------------------------------
# conda-native wiring (#311 P2-δ): --conda flag, worker threading, report
# --------------------------------------------------------------------------

def test_conda_default_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ONLYCODES_CONDA_BUILD", raising=False)
    assert vvs._conda_default() is False
    for truthy in ("1", "true", "YES", "on"):
        monkeypatch.setenv("ONLYCODES_CONDA_BUILD", truthy)
        assert vvs._conda_default() is True
    for falsey in ("0", "no", "", "off"):
        monkeypatch.setenv("ONLYCODES_CONDA_BUILD", falsey)
        assert vvs._conda_default() is False


@pytest.mark.parametrize("conda", [True, False])
def test_worker_script_threads_conda_and_compiles(conda: bool) -> None:
    """The per-instance worker template must embed the conda flag and compile
    for both values — brace-escaping in the f-string-free .format() is fragile."""
    code = vvs.WORKER_SCRIPT.format(
        repo_root="/repo", yaml_path="/repo/x.yaml",
        clone_base="/tmp/cb", force=False, conda=conda,
    )
    compile(code, "<worker>", "exec")
    assert f"conda = {conda}" in code
    # Gate 1 builds via the conda-aware path…
    assert "_setup_one(problem, force=force, conda=conda)" in code
    # …and Gate 2 layers the spec's eval_commands env over the hand-table.
    assert "specs.eval_env(spec)" in code
    assert "specs.eval_system_commands(spec)" in code
    assert "_INSTANCE_ENV.get(iid)" in code


def test_write_summary_notes_build_path(tmp_path: Path) -> None:
    import datetime as dt
    start = dt.datetime(2026, 6, 3, tzinfo=dt.timezone.utc)

    venv_out = tmp_path / "venv.md"
    vvs.write_summary(_results(), venv_out, set_name="swe/swebench-verified",
                      start=start, pool_size=4, conda=False)
    assert "Build path: **venv (generic)**" in venv_out.read_text()

    conda_out = tmp_path / "conda.md"
    vvs.write_summary(_results(), conda_out, set_name="swe/swebench-verified",
                      start=start, pool_size=4, conda=True)
    text = conda_out.read_text()
    assert "conda-native (spec-faithful" in text
    # the conda-only Gate-2 fidelity note is present
    assert "eval_commands" in text and "locale-gen" in text
