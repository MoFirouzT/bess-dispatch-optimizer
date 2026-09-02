"""Property tests for R2.7: study windowing.

Contract: docs/specs/study-windowing.md § "Property tests".

The golden oracles pin the filter invariant on hand-chosen selections; these pin it
over arbitrary ones, for every study that reports a per-window distribution, and pin
the fold layout and the block bootstrap that the live gates rest on.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bess.assets.battery import BatterySpec
from bess.data.fixtures import synthetic_day_ahead
from bess.forecaster.evaluate import rolling_origin_folds
from bess.studies import (
    bid_curve_value_across_windows,
    fold_days,
    summarize_by_block,
    summarize_by_year,
    tail_value_across_windows,
    vss_across_windows,
)
from bess.studies.windows import window_sets

TOL = 1e-9
_BATT = BatterySpec(capacity=2.0, soc_initial=0.5, soc_terminal=0.5)


# ------------------------------------------------------------- the filter invariant


@settings(max_examples=25, deadline=None)
@given(st.data())
def test_window_selection_is_a_filter_for_any_subset(data) -> None:
    """For an arbitrary subset of days that can be scored, selection returns exactly that subset."""
    prices = synthetic_day_ahead(days=55, seed=11)
    full = window_sets(prices, history_days=28, n_scenarios=30, seed=0)
    starts = [w[0] for w in full]

    picked = data.draw(st.lists(st.sampled_from(starts), min_size=1, max_size=8, unique=True))
    picked = sorted(picked)

    subset = window_sets(
        prices, history_days=28, n_scenarios=30, seed=0, only_days=pd.DatetimeIndex(picked)
    )

    assert [w[0] for w in subset] == picked
    by_start = {w[0]: w for w in full}
    for start, train, evaluation in subset:
        np.testing.assert_array_equal(train.paths, by_start[start][1].paths)
        np.testing.assert_array_equal(evaluation.paths, by_start[start][2].paths)


def test_unknown_days_are_ignored_not_invented() -> None:
    """Days outside the set that can be scored drop out; they never create an empty window.

    A caller passing a fold layout wider than the series (or a day inside the history
    head) must get the intersection, not a crash and not a padded window.
    """
    prices = synthetic_day_ahead(days=40, seed=2)
    full = window_sets(prices, seed=0)
    good = full[0][0]
    outside = pd.DatetimeIndex([good, good - pd.Timedelta(days=400), good + pd.Timedelta(days=400)])

    subset = window_sets(prices, seed=0, only_days=outside)

    assert [w[0] for w in subset] == [good]


@pytest.mark.parametrize(
    "fn,kwargs",
    [
        (vss_across_windows, dict(rho=0.5)),
        (tail_value_across_windows, dict(rho=0.5)),
        (bid_curve_value_across_windows, dict(rho=0.5)),
    ],
)
def test_study_selection_commutes_with_scoring(fn, kwargs) -> None:
    """Scoring a subset equals subsetting the full scoring, for every swept study.

    `fv_across_windows` is exercised the same way in the live tier: it needs the
    forecast group, and its refit cadence makes it too slow for a property test.
    """
    prices = synthetic_day_ahead(days=42, seed=13)
    full = fn(prices, _BATT, history_days=28, seed=0, **kwargs)
    assert len(full) >= 6

    picked = pd.DatetimeIndex([full[i].window_start for i in (0, 2, 5)])
    subset = fn(prices, _BATT, history_days=28, seed=0, only_days=picked, **kwargs)

    by_start = {w.window_start: w for w in full}
    assert [w.window_start for w in subset] == list(picked)
    for w in subset:
        assert w == by_start[w.window_start]


def test_a_windows_result_is_independent_of_the_enclosing_span() -> None:
    """The same day scored inside a short and a long series gives the same numbers.

    This is the invariant the pre-R2.7 ordinal seeding violates, stated at the study
    level: without it, a fold-selected distribution and a swept one are two different
    experiments wearing the same name.
    """
    long_prices = synthetic_day_ahead(days=80, seed=17)
    short_prices = long_prices.loc[long_prices.index[24 * 15] :]

    day = pd.DatetimeIndex(short_prices.index).normalize()[0] + pd.Timedelta(days=30)
    pick = pd.DatetimeIndex([day])

    (a,) = vss_across_windows(long_prices, _BATT, rho=0.5, seed=0, only_days=pick)
    (b,) = vss_across_windows(short_prices, _BATT, rho=0.5, seed=0, only_days=pick)

    assert a == b


# ------------------------------------------------------------------ fold placement


@given(
    n_folds=st.integers(min_value=2, max_value=12),
    test_days=st.integers(min_value=1, max_value=7),
)
@settings(max_examples=40, deadline=None)
def test_fold_blocks_are_disjoint_and_have_history(n_folds, test_days) -> None:
    """Blocks never overlap, and every block has a full training window before it."""
    days = pd.date_range("2021-01-01", periods=900, freq="D", tz="UTC")
    train_days = 90
    folds = rolling_origin_folds(
        days, n_folds=n_folds, test_days=test_days, train_days=train_days, spacing="even"
    )

    selected = fold_days(folds)
    assert len(selected) == n_folds * test_days  # no day counted twice
    assert selected.is_monotonic_increasing

    for f in folds:
        assert days.get_loc(f.test_start) >= train_days
        assert f.train_end <= f.test_start


def test_fold_days_over_complete_days_only_is_fully_scoreable() -> None:
    """Placing folds over complete days makes every selected day a window that can be scored.

    Build task 0's finding: a span whose final day is partial selects a day that
    `window_sets` then drops, so the promised window count exceeds the delivered one.
    """
    prices = synthetic_day_ahead(days=200, seed=19)
    partial = prices.iloc[:-23]  # final day left with one hour

    idx = pd.DatetimeIndex(partial.index)
    raw_days = pd.DatetimeIndex(sorted(set(idx.normalize())))
    complete = pd.DatetimeIndex([d for d, c in partial.groupby(idx.normalize()) if len(c) == 24])
    assert len(complete) == len(raw_days) - 1

    kw = dict(n_folds=4, test_days=5, train_days=60, spacing="even")
    raw_sel = fold_days(rolling_origin_folds(raw_days, **kw))
    complete_sel = fold_days(rolling_origin_folds(complete, **kw))

    scored_raw = window_sets(partial, seed=0, only_days=raw_sel)
    scored_complete = window_sets(partial, seed=0, only_days=complete_sel)

    assert len(scored_raw) < len(raw_sel)  # the silent shortfall
    assert len(scored_complete) == len(complete_sel)  # what the layout promised


# --------------------------------------------------------------- block bootstrap


@given(
    values=st.lists(
        st.floats(min_value=-500, max_value=500, allow_nan=False), min_size=12, max_size=60
    ),
    seed=st.integers(min_value=0, max_value=5),
)
@settings(max_examples=30, deadline=None)
def test_bootstrap_interval_brackets_the_point_median(values, seed) -> None:
    """The resampled interval contains the median it is an interval for."""
    v = np.array(values)
    blocks = np.arange(len(v)) // 3

    s = summarize_by_block(v, blocks, n_boot=300, seed=seed)

    assert s.median_ci[0] <= s.median + TOL
    assert s.median >= s.median_ci[0] - TOL
    assert s.median <= s.median_ci[1] + TOL
    assert s.n_windows == len(v)


def test_bootstrap_is_deterministic_under_a_fixed_seed() -> None:
    """Same inputs and seed, same interval: a gate that drifts run to run is not a gate."""
    rng = np.random.default_rng(0)
    v = rng.normal(5.0, 20.0, size=48)
    blocks = np.arange(48) // 4

    a = summarize_by_block(v, blocks, n_boot=400, seed=3)
    b = summarize_by_block(v, blocks, n_boot=400, seed=3)

    assert a == b


def test_more_blocks_narrow_the_interval() -> None:
    """Resampling more blocks from the same population tightens the median interval.

    Not a strict per-draw guarantee, so this compares a 4-block sample against a
    52-block one from the same generator, where the gap is far outside sampling noise.
    """
    rng = np.random.default_rng(1)
    draw = lambda n: rng.normal(10.0, 30.0, size=n * 5)  # noqa: E731

    few = summarize_by_block(draw(4), np.arange(20) // 5, n_boot=800, seed=0)
    many = summarize_by_block(draw(52), np.arange(260) // 5, n_boot=800, seed=0)

    assert (many.median_ci[1] - many.median_ci[0]) < (few.median_ci[1] - few.median_ci[0])


def test_single_block_reports_no_interval() -> None:
    """One block cannot support a between-block interval, and says so rather than lying.

    Reporting a zero-width CI here would claim certainty from a sample of one block.
    """
    v = np.array([1.0, 2.0, 3.0, 4.0])
    s = summarize_by_block(v, np.zeros(4, dtype=int), n_boot=200, seed=0)

    assert s.n_windows == 4
    assert np.isnan(s.median_ci[0]) and np.isnan(s.median_ci[1])


# ------------------------------------------------------------------ regime split


@given(n=st.integers(min_value=5, max_value=200), offset=st.integers(min_value=0, max_value=400))
@settings(max_examples=40, deadline=None)
def test_year_partition_is_exhaustive_and_disjoint(n, offset) -> None:
    """Per-year window counts sum to the total, for any run of consecutive days."""
    starts = pd.date_range("2022-06-01", periods=n, freq="D", tz="UTC") + pd.Timedelta(days=offset)
    values = np.arange(n, dtype=float)

    by_year = summarize_by_year(values, list(starts))

    assert sum(s.n_windows for s in by_year.values()) == n
    assert set(by_year) == set(starts.year)
