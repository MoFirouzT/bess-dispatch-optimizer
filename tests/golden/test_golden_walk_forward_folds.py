"""Golden oracles for R2.1d walk-forward fold placement and the coverage bootstrap.

Spec: ``docs/specs/R2.1d-evaluation-honesty.md`` § "Golden oracles". Unlike the rest
of forecasting, fold placement is exact arithmetic, so these are hand-derived oracles
rather than statistical gates: given a span and a fold request, *which* days train and
*which* days are tested is fully determined, and so is the no-leakage boundary.

Oracle 1 is the backward-compatibility pin. The R2.1 harness took the last
``n_folds * test_days`` days as contiguous blocks; that behavior is preserved exactly
under ``spacing="contiguous"``, so the historical R2.1 coverage number stays
reproducible as arithmetic rather than as a memory.

Pure pandas/numpy: no LightGBM or MAPIE, so these run in the CI tier without the
``forecast`` dependency group.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bess.forecaster.evaluate import coverage_ci, rolling_origin_folds


def _days(n: int, start: str = "2021-01-01") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="D", tz="UTC")


def test_oracle1_contiguous_placement_reproduces_the_r21_blocks():
    """R2.1 took the last n_folds*test_days days as contiguous blocks. Pinned exactly.

    100 days, 3 folds of 5: the old code computed
    ``start = len(days) - 15 + fold*5`` giving day indices 85, 90, 95. Each block runs
    to ``start + test_days - 1`` inclusive, and training is everything strictly before
    the block (expanding, from day 0).

    The compatibility path is selected explicitly: ``rolling_origin_folds`` defaults
    to the R2.1d placement (``spacing="even"``), while ``walk_forward_coverage`` keeps
    ``"contiguous"`` as its default so existing callers are unchanged.
    """
    days = _days(100)
    folds = rolling_origin_folds(
        days, n_folds=3, test_days=5, train_days=None, spacing="contiguous"
    )

    assert [f.test_start for f in folds] == [days[85], days[90], days[95]]
    assert [f.test_end for f in folds] == [days[89], days[94], days[99]]
    # Expanding window: every fold trains from the very first day up to its block.
    assert [f.train_start for f in folds] == [days[0], days[0], days[0]]
    assert [f.train_end for f in folds] == [days[85], days[90], days[95]]


def test_oracle2_even_spacing_with_a_rolling_window():
    """1000 days, 10 folds of 5, 365-day rolling training window.

    The earliest test day is index 365 (a full training window must precede it) and
    the latest block must end on the last day, index 999, so its start is index 995.
    Ten folds spread inclusively over [365, 995] step by (995-365)/9 = 70 exactly.
    """
    days = _days(1000)
    folds = rolling_origin_folds(days, n_folds=10, test_days=5, train_days=365)

    assert len(folds) == 10
    assert [days.get_loc(f.test_start) for f in folds] == [365 + 70 * i for i in range(10)]
    assert folds[0].test_start == days[365]
    assert folds[-1].test_end == days[999]
    # Rolling, not expanding: the window slides with the block.
    assert folds[0].train_start == days[0]
    assert folds[-1].train_start == days[995 - 365]


def test_oracle3_a_span_too_short_for_the_request_raises():
    """400 days cannot host 52 non-overlapping 5-day blocks after a 365-day warm-up.

    Test starts are confined to [365, 395], a 30-day range; 52 folds need at least
    51*5 = 255 days of spread. The generator must refuse rather than silently overlap
    folds, which would pool the same test day into the coverage statistic twice.
    """
    days = _days(400)
    with pytest.raises(ValueError, match="cannot host"):
        rolling_origin_folds(days, n_folds=52, test_days=5, train_days=365)


def test_oracle4_no_leakage_and_fixed_training_length():
    """Every fold of oracle 2 trains strictly before it tests, on exactly 365 days."""
    days = _days(1000)
    folds = rolling_origin_folds(days, n_folds=10, test_days=5, train_days=365)

    for f in folds:
        # train_end is exclusive: training uses days strictly earlier than the block.
        assert f.train_end <= f.test_start
        assert f.train_start < f.train_end
        assert (f.train_end - f.train_start).days == 365
        assert (f.test_end - f.test_start).days == 4  # 5 days inclusive


def test_oracle5_day_block_bootstrap_matches_the_analytic_binomial_spread():
    """100 days, each wholly covered or wholly missed, 50/50: a known-answer case.

    When the coverage indicator is constant within a day, pooled coverage is exactly
    the fraction of covered *days*, so the day-block bootstrap is sampling a binomial
    proportion with n=100 and p=0.5. Its standard error is sqrt(0.25/100) = 0.05, so a
    95% interval spans about 2*1.96*0.05 = 0.196. That is hand-derivable, which is what
    makes this an oracle rather than a self-fulfilling check of the code's own output.
    """
    per_day = [
        np.ones(24, dtype=bool) if i % 2 == 0 else np.zeros(24, dtype=bool) for i in range(100)
    ]

    lo, hi = coverage_ci(per_day, level=0.95, n_boot=2000, seed=0)

    pooled = float(np.concatenate(per_day).mean())
    assert pooled == 0.5
    assert lo < 0.5 < hi
    analytic_width = 2 * 1.96 * 0.05
    assert abs((hi - lo) - analytic_width) < 0.02, (
        f"bootstrap width {hi - lo:.4f} far from the analytic binomial width "
        f"{analytic_width:.4f}; the resampler is not sampling whole days"
    )
