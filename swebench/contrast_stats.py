"""Paired contrast statistics for arm-vs-arm comparison (#299, #307).

The SWE-bench/Claude cost anomaly the four-cell narrative pivots on is a
**paired** comparison: the same instances run under both arms, so we test the
within-instance difference rather than the unpaired between-arm difference.
Pairing removes the order-of-magnitude between-instance cost variance and is
materially more powerful — it is the right model for the data the harness
already collects.

Cost is multiplicative and the headline contrast is a percentage (e.g.
``+14.4%``), so cost contrasts are computed on the **log scale**
(``d_i = log cost_treatment,i - log cost_reference,i``) and reported as
``exp(mean d) - 1``. Because cost is heavy-tailed (a few instances dominate),
the CI/p-value come from a **paired bootstrap**, not a Student t-test; Wilcoxon
signed-rank is offered as a distribution-free cross-check.

No ``statsmodels`` dependency — ``numpy`` for the bootstrap, ``scipy.stats`` for
Wilcoxon and the exact binomial (McNemar), so the only new repo dependency is
``scipy`` (already transitively present via scikit-learn).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


# ---------------------------------------------------------------------------
# Pairing
# ---------------------------------------------------------------------------


def paired_log_diffs(
    treatment: dict[str, float],
    reference: dict[str, float],
) -> tuple[list[str], np.ndarray, int]:
    """Align two ``{instance_id: cost}`` maps into per-instance log-ratios.

    Returns ``(instance_ids, d, n_dropped)`` where ``d[i] = log(treatment) -
    log(reference)`` over the instances present in **both** maps with strictly
    positive cost in both. Instances missing on either side, or with a
    non-positive / non-finite cost, are dropped and counted in ``n_dropped``
    (so the caller can surface coverage rather than silently shrinking N).
    ``instance_ids`` is sorted for determinism.
    """
    common = sorted(set(treatment) & set(reference))
    ids: list[str] = []
    diffs: list[float] = []
    dropped = 0
    for iid in common:
        a = treatment[iid]
        b = reference[iid]
        if a is None or b is None or a <= 0 or b <= 0 or not (math.isfinite(a) and math.isfinite(b)):
            dropped += 1
            continue
        ids.append(iid)
        diffs.append(math.log(a) - math.log(b))
    # instances present in only one arm also count as "dropped" coverage gaps
    dropped += len(set(treatment) ^ set(reference))
    return ids, np.asarray(diffs, dtype=float), dropped


# ---------------------------------------------------------------------------
# Paired bootstrap on log-differences
# ---------------------------------------------------------------------------


@dataclass
class ContrastResult:
    """Result of a paired cost contrast on the log scale."""

    n: int
    mean_log_diff: float
    pct_effect: float          # exp(mean_log_diff) - 1, in percent
    ci_pct: tuple[float, float]  # bootstrap CI for pct_effect, in percent
    p_bootstrap: float
    p_wilcoxon: float | None
    n_dropped: int = 0
    n_boot: int = 0
    alpha: float = 0.05

    def as_dict(self) -> dict:
        lo, hi = self.ci_pct
        return {
            "n": self.n,
            "n_dropped": self.n_dropped,
            "mean_log_diff": self.mean_log_diff,
            "pct_effect": self.pct_effect,
            "ci_pct_lo": lo,
            "ci_pct_hi": hi,
            "p_bootstrap": self.p_bootstrap,
            "p_wilcoxon": self.p_wilcoxon,
            "n_boot": self.n_boot,
            "alpha": self.alpha,
            "significant": (self.p_bootstrap is not None and self.p_bootstrap < self.alpha),
        }


def _bootstrap_means(d: np.ndarray, n_boot: int, seed: int) -> np.ndarray:
    """Bootstrap distribution of the mean of ``d`` (paired resample of instances)."""
    rng = np.random.default_rng(seed)
    n = len(d)
    # idx shape (n_boot, n): each row is one resample of instance indices.
    idx = rng.integers(0, n, size=(n_boot, n))
    return d[idx].mean(axis=1)


def paired_cost_contrast(
    treatment: dict[str, float],
    reference: dict[str, float],
    *,
    n_boot: int = 10000,
    alpha: float = 0.05,
    seed: int = 0,
) -> ContrastResult:
    """Paired cost contrast (treatment vs reference) on the log scale.

    The point estimate is ``exp(mean log-ratio) - 1`` (percent). The CI is the
    percentile bootstrap of that quantity; the bootstrap p-value is the
    standard two-sided CI-inversion ``2 * min(P(boot<=0), P(boot>=0))``. A
    Wilcoxon signed-rank p-value is included as a distribution-free check
    (``None`` when n is too small or all differences are zero).
    """
    ids, d, dropped = paired_log_diffs(treatment, reference)
    n = len(d)
    if n == 0:
        return ContrastResult(
            n=0, mean_log_diff=float("nan"), pct_effect=float("nan"),
            ci_pct=(float("nan"), float("nan")), p_bootstrap=float("nan"),
            p_wilcoxon=None, n_dropped=dropped, n_boot=0, alpha=alpha,
        )

    mean_log = float(d.mean())
    boot = _bootstrap_means(d, n_boot, seed)
    lo_log, hi_log = np.percentile(boot, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    # CI-inversion two-sided bootstrap p-value.
    p_left = float(np.mean(boot >= 0.0))
    p_right = float(np.mean(boot <= 0.0))
    p_boot = min(1.0, 2.0 * min(p_left, p_right))

    p_wil = wilcoxon_pvalue(d)

    return ContrastResult(
        n=n,
        mean_log_diff=mean_log,
        pct_effect=100.0 * (math.exp(mean_log) - 1.0),
        ci_pct=(100.0 * (math.exp(lo_log) - 1.0), 100.0 * (math.exp(hi_log) - 1.0)),
        p_bootstrap=p_boot,
        p_wilcoxon=p_wil,
        n_dropped=dropped,
        n_boot=n_boot,
        alpha=alpha,
    )


def wilcoxon_pvalue(d: np.ndarray) -> float | None:
    """Two-sided Wilcoxon signed-rank p-value, or ``None`` if undefined.

    scipy raises when every difference is zero (no signed ranks) and warns for
    very small n; we return ``None`` in the degenerate cases rather than
    propagate an exception into the report.
    """
    nz = d[d != 0.0]
    if len(nz) < 1:
        return None
    try:
        from scipy.stats import wilcoxon
        return float(wilcoxon(nz).pvalue)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Equivalence (the "cleanly null under adequate power" branch)
# ---------------------------------------------------------------------------


@dataclass
class EquivalenceResult:
    equivalent: bool
    ci_pct: tuple[float, float]   # (1-2 alpha) CI for pct effect
    bound_pct: tuple[float, float]
    n: int

    def as_dict(self) -> dict:
        lo, hi = self.ci_pct
        blo, bhi = self.bound_pct
        return {
            "equivalent": self.equivalent,
            "tost_ci_pct_lo": lo,
            "tost_ci_pct_hi": hi,
            "bound_pct_lo": blo,
            "bound_pct_hi": bhi,
            "n": self.n,
        }


def equivalence_tost(
    treatment: dict[str, float],
    reference: dict[str, float],
    *,
    bound_pct: float = 10.0,
    n_boot: int = 10000,
    alpha: float = 0.05,
    seed: int = 0,
) -> EquivalenceResult:
    """Bootstrap TOST equivalence test on the log-scale cost contrast.

    Equivalence to "no meaningful effect" is declared when the central
    ``(1 - 2*alpha)`` bootstrap CI for the percent effect lies entirely within
    ``±bound_pct`` (the CI-inclusion form of two one-sided tests). This is the
    "cleanly null under adequate power" verdict for #299: a tight CI that
    excludes a pre-registered meaningful effect (default ±10%) retires the
    "lone exception" framing honestly, rather than chasing a vanishing effect.
    """
    ids, d, _ = paired_log_diffs(treatment, reference)
    n = len(d)
    if n == 0:
        return EquivalenceResult(False, (float("nan"), float("nan")),
                                 (-bound_pct, bound_pct), 0)
    boot = _bootstrap_means(d, n_boot, seed)
    # (1-2 alpha) CI: TOST is equivalent to the 90% CI (for alpha=0.05) being inside bounds.
    lo_log, hi_log = np.percentile(boot, [100 * alpha, 100 * (1 - alpha)])
    lo_pct = 100.0 * (math.exp(lo_log) - 1.0)
    hi_pct = 100.0 * (math.exp(hi_log) - 1.0)
    equivalent = (lo_pct >= -bound_pct) and (hi_pct <= bound_pct)
    return EquivalenceResult(equivalent, (lo_pct, hi_pct), (-bound_pct, bound_pct), n)


# ---------------------------------------------------------------------------
# McNemar pass-rate guard
# ---------------------------------------------------------------------------


@dataclass
class McNemarResult:
    n: int
    b: int          # treatment PASS, reference FAIL
    c: int          # treatment FAIL, reference PASS
    p_value: float
    pass_rate_treatment: float
    pass_rate_reference: float

    def as_dict(self) -> dict:
        return {
            "n": self.n,
            "discordant_treatment_only": self.b,
            "discordant_reference_only": self.c,
            "mcnemar_p": self.p_value,
            "pass_rate_treatment": self.pass_rate_treatment,
            "pass_rate_reference": self.pass_rate_reference,
        }


def mcnemar_from_passes(
    pass_treatment: dict[str, bool],
    pass_reference: dict[str, bool],
) -> McNemarResult:
    """Paired pass-rate guard via an exact-binomial McNemar test.

    The cost contrast is only interpretable if the two arms solve the same
    problems — a capability gap would confound it. ``b``/``c`` are the
    discordant pairs; the exact two-sided binomial test on ``min(b,c)`` of
    ``b+c`` trials at p=0.5 avoids the chi-square approximation that is invalid
    for small discordant counts. ``p_value`` is 1.0 when there are no
    discordant pairs.
    """
    common = sorted(set(pass_treatment) & set(pass_reference))
    b = sum(1 for i in common if pass_treatment[i] and not pass_reference[i])
    c = sum(1 for i in common if not pass_treatment[i] and pass_reference[i])
    n = len(common)
    if b + c == 0:
        p = 1.0
    else:
        try:
            from scipy.stats import binomtest
            p = float(binomtest(min(b, c), b + c, 0.5).pvalue)
        except Exception:
            p = float("nan")
    pr_t = (sum(1 for i in common if pass_treatment[i]) / n) if n else float("nan")
    pr_r = (sum(1 for i in common if pass_reference[i]) / n) if n else float("nan")
    return McNemarResult(n=n, b=b, c=c, p_value=p,
                         pass_rate_treatment=pr_t, pass_rate_reference=pr_r)
