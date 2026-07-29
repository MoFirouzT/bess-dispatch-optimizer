"""Golden oracles for R2.8: seed reproducibility (formulation §R2.5).

Contract: docs/specs/draw-noise.md § "Golden oracles".

The width these pin is a **reproducibility** statement, not a confidence interval: run
the published command again with a different seed and the answer moves this far. The
oracles fix the arithmetic and, more importantly, the two boundary behaviours that
decide whether the number can be trusted: a deterministic study must report exactly
zero width, and a single run must refuse to report one at all.
"""

from __future__ import annotations

import math

import pytest

from bess.studies import summarize_across_seeds

TOL = 1e-12


def test_oracle_1_hand_computed_spread() -> None:
    """Medians 1, 3, 5: mean 3, population sd sqrt(8/3), range [1, 5], spread 4.

    The sd is the **population** form (ddof=0), not the sample form. These K runs are
    the whole set of runs performed, not a sample drawn from a larger population of
    runs, so dividing by K is the honest choice and sqrt(8/3) rather than sqrt(4)
    is what pins it.
    """
    s = summarize_across_seeds({0: 1.0, 1: 3.0, 2: 5.0})

    assert s.n_seeds == 3
    assert s.mean_median == pytest.approx(3.0, abs=TOL)
    assert s.sd_median == pytest.approx(math.sqrt(8.0 / 3.0), abs=1e-9)
    assert s.min_median == pytest.approx(1.0, abs=TOL)
    assert s.max_median == pytest.approx(5.0, abs=TOL)
    assert s.spread == pytest.approx(4.0, abs=TOL)


def test_oracle_2_identical_seeds_report_no_width() -> None:
    """A study that ignores its seed reports exactly zero, not a small number.

    Worth pinning because the alternative failure is silent: a width of 1e-16 printed
    as "0.00" reads identically to a real zero, and the two mean different things.
    """
    s = summarize_across_seeds({7: 2.5, 8: 2.5, 9: 2.5, 10: 2.5})

    assert s.sd_median == 0.0
    assert s.spread == 0.0
    assert s.mean_median == pytest.approx(2.5, abs=TOL)


def test_oracle_3_two_seeds_is_the_documented_minimum() -> None:
    """Two runs are enough to state a width, and the boundary is pinned deliberately."""
    s = summarize_across_seeds({0: 12.90, 1: 9.12})

    assert s.n_seeds == 2
    assert s.spread == pytest.approx(3.78, abs=1e-9)
    assert s.mean_median == pytest.approx(11.01, abs=1e-9)


def test_oracle_4_one_seed_refuses_rather_than_returning_zero() -> None:
    """A spread over a single run must raise.

    Returning 0.0 would be the dangerous answer: it is indistinguishable from a
    genuinely reproducible study, so a caller who forgot to vary the seed would publish
    "no seed sensitivity" having measured nothing.
    """
    with pytest.raises(ValueError, match="at least 2 seeds"):
        summarize_across_seeds({0: 12.90})


def test_oracle_5_non_finite_median_is_rejected() -> None:
    """A nan from a failed run must not become a published width."""
    with pytest.raises(ValueError, match="finite"):
        summarize_across_seeds({0: 1.0, 1: float("nan")})
