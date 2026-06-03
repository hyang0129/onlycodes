"""Unit tests for swebench.contrast_stats (#299 significance report).

Hermetic and fast: synthetic per-instance cost/verdict maps with known sign
and magnitude. No run dirs, no network.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from swebench.contrast_stats import (
    equivalence_tost,
    mcnemar_from_passes,
    paired_cost_contrast,
    paired_log_diffs,
    wilcoxon_pvalue,
)


# --- paired_log_diffs -------------------------------------------------------


def test_paired_log_diffs_alignment_and_value():
    treat = {"a": 1.144, "b": 2.288}
    ref = {"a": 1.0, "b": 2.0}
    ids, d, dropped = paired_log_diffs(treat, ref)
    assert ids == ["a", "b"]
    assert dropped == 0
    # Both ratios are 1.144 → identical log-diffs.
    assert d == pytest.approx([math.log(1.144), math.log(1.144)])


def test_paired_log_diffs_drops_missing_and_nonpositive():
    treat = {"a": 1.0, "b": 2.0, "c": 3.0, "only_t": 1.0}
    ref = {"a": 1.0, "b": 0.0, "c": -1.0, "only_r": 1.0}
    ids, d, dropped = paired_log_diffs(treat, ref)
    # 'a' kept; 'b' (zero) and 'c' (negative) dropped; only_t/only_r are coverage gaps.
    assert ids == ["a"]
    assert len(d) == 1
    # 2 non-positive in common + 2 single-arm-only = 4 dropped
    assert dropped == 4


# --- paired_cost_contrast ---------------------------------------------------


def test_contrast_recovers_known_positive_effect():
    # Every instance costs 14.4% more under treatment → exact recovery.
    ref = {f"i{k}": 1.0 + 0.01 * k for k in range(40)}
    treat = {k: 1.144 * v for k, v in ref.items()}
    res = paired_cost_contrast(treat, ref, n_boot=2000, seed=0)
    assert res.n == 40
    assert res.pct_effect == pytest.approx(14.4, abs=1e-6)
    lo, hi = res.ci_pct
    assert lo == pytest.approx(14.4, abs=1e-6) and hi == pytest.approx(14.4, abs=1e-6)
    assert res.p_bootstrap == pytest.approx(0.0, abs=1e-9)
    assert res.as_dict()["significant"] is True


def test_contrast_null_effect_not_significant():
    ref = {f"i{k}": 1.0 + 0.01 * k for k in range(40)}
    treat = dict(ref)  # identical → zero effect
    res = paired_cost_contrast(treat, ref, n_boot=2000, seed=0)
    assert res.pct_effect == pytest.approx(0.0, abs=1e-9)
    assert res.p_bootstrap == pytest.approx(1.0)
    assert res.p_wilcoxon is None  # all-zero differences
    assert res.as_dict()["significant"] is False


def test_contrast_noisy_positive_is_significant_and_correct_sign():
    rng = np.random.default_rng(42)
    ref = {f"i{k}": float(rng.uniform(0.5, 5.0)) for k in range(200)}
    # +20% mean log effect with noise; with n=200 this separates cleanly.
    treat = {k: v * math.exp(0.20 + rng.normal(0, 0.1)) for k, v in ref.items()}
    res = paired_cost_contrast(treat, ref, n_boot=4000, seed=1)
    assert res.pct_effect > 0
    assert res.ci_pct[0] > 0  # CI excludes zero from below
    assert res.p_bootstrap < 0.05


def test_contrast_bootstrap_is_seed_deterministic():
    ref = {f"i{k}": 1.0 + 0.05 * k for k in range(30)}
    treat = {k: v * math.exp(0.1 * ((i % 5) - 2)) for i, (k, v) in enumerate(ref.items())}
    a = paired_cost_contrast(treat, ref, n_boot=1500, seed=7)
    b = paired_cost_contrast(treat, ref, n_boot=1500, seed=7)
    assert a.ci_pct == b.ci_pct and a.p_bootstrap == b.p_bootstrap


def test_contrast_empty_overlap_is_nan_not_crash():
    res = paired_cost_contrast({"a": 1.0}, {"b": 1.0}, n_boot=100)
    assert res.n == 0
    assert math.isnan(res.pct_effect)


# --- wilcoxon ---------------------------------------------------------------


def test_wilcoxon_none_when_all_zero():
    assert wilcoxon_pvalue(np.zeros(10)) is None


# --- equivalence (TOST) -----------------------------------------------------


def test_equivalence_tight_null_is_equivalent():
    # Effect ~0 with tiny noise and large n → 90% CI well inside ±10%.
    rng = np.random.default_rng(0)
    ref = {f"i{k}": float(rng.uniform(1, 4)) for k in range(300)}
    treat = {k: v * math.exp(rng.normal(0, 0.01)) for k, v in ref.items()}
    eq = equivalence_tost(treat, ref, bound_pct=10.0, n_boot=3000, seed=0)
    assert eq.equivalent is True
    assert -10.0 < eq.ci_pct[0] and eq.ci_pct[1] < 10.0


def test_equivalence_large_effect_not_equivalent():
    ref = {f"i{k}": 1.0 + 0.01 * k for k in range(40)}
    treat = {k: 1.3 * v for k, v in ref.items()}  # +30% > ±10% bound
    eq = equivalence_tost(treat, ref, bound_pct=10.0, n_boot=2000, seed=0)
    assert eq.equivalent is False


# --- McNemar pass-rate guard ------------------------------------------------


def test_mcnemar_counts_discordant_pairs():
    # 5 both-pass, b=8 treatment-only, c=1 reference-only, 2 both-fail.
    pass_t, pass_r = {}, {}
    k = 0
    for _ in range(5):
        pass_t[f"i{k}"], pass_r[f"i{k}"] = True, True; k += 1
    for _ in range(8):
        pass_t[f"i{k}"], pass_r[f"i{k}"] = True, False; k += 1
    for _ in range(1):
        pass_t[f"i{k}"], pass_r[f"i{k}"] = False, True; k += 1
    for _ in range(2):
        pass_t[f"i{k}"], pass_r[f"i{k}"] = False, False; k += 1
    res = mcnemar_from_passes(pass_t, pass_r)
    assert res.b == 8 and res.c == 1 and res.n == 16
    assert res.pass_rate_treatment == pytest.approx(13 / 16)
    assert res.pass_rate_reference == pytest.approx(6 / 16)
    assert 0.0 < res.p_value < 1.0


def test_mcnemar_no_discordant_is_p1():
    pass_t = {"a": True, "b": False}
    pass_r = {"a": True, "b": False}
    res = mcnemar_from_passes(pass_t, pass_r)
    assert res.b == 0 and res.c == 0
    assert res.p_value == 1.0
