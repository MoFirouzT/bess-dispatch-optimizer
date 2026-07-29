"""Golden oracles for R2.7: study windowing (formulation §R2.5).

Contract: docs/specs/study-windowing.md § "Golden oracles".

The phase's load-bearing claim is that **selection is a filter, not a
re-parameterization**: scoring a chosen set of delivery days must return exactly what
scoring every day and discarding the rest returns. Without it a fold-selected result
is not comparable to a swept one, and the whole re-measurement means nothing.

Oracles 2 and 3 pin that invariant bitwise, at the window source and again at the
study level. Oracle 1 pins the fold placement arithmetic, and 4 to 6 pin the summary
statistics the studies pages quote. All token-free and forecast-group-free.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bess.assets.battery import BatterySpec
from bess.data.fixtures import synthetic_day_ahead
from bess.forecaster.evaluate import rolling_origin_folds
from bess.studies import fold_days, summarize_by_block, summarize_by_year, vss_across_windows
from bess.studies.windows import window_sets

TOL = 1e-9

# Same battery as the R2.3 designed-instance gate and the R2.5 study.
_BATT = BatterySpec(capacity=2.0, soc_initial=0.5, soc_terminal=0.5)


def _days(n: int, start: str = "2021-01-01") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="D", tz="UTC")


# --------------------------------------------------------------- fold placement


def test_oracle_1_fold_days_exact() -> None:
    """400 days, 4 folds of 5, `train_days=90`, even spacing: the 20 dates by hand.

    `rolling_origin_folds` places the earliest start at index `train_days` (90) and
    the latest at `len(days) - test_days` (395), then spreads the rest evenly:
    step = (395 - 90) / 3 = 101.67, so starts land at 90, 192, 293, 395. Each block
    runs five consecutive days from its start.
    """
    days = _days(400)
    folds = rolling_origin_folds(days, n_folds=4, test_days=5, train_days=90, spacing="even")

    assert [days.get_loc(f.test_start) for f in folds] == [90, 192, 293, 395]

    expected = pd.DatetimeIndex(
        [d for s in (90, 192, 293, 395) for d in days[s : s + 5]]
    ).sort_values()
    pd.testing.assert_index_equal(fold_days(folds), expected)
    assert len(fold_days(folds)) == 20


def test_oracle_1b_fold_days_dedupes_and_sorts() -> None:
    """Overlapping folds contribute each day once; the result is sorted.

    `rolling_origin_folds` never emits overlapping blocks, but `fold_days` is a pure
    set union and must not depend on that: a duplicated day would double-weight a
    window in every downstream distribution.
    """
    days = _days(400)
    folds = rolling_origin_folds(days, n_folds=4, test_days=5, train_days=90, spacing="even")
    doubled = list(folds) + list(folds)

    pd.testing.assert_index_equal(fold_days(doubled), fold_days(folds))
    assert fold_days(doubled).is_monotonic_increasing


# ------------------------------------------- selection is a filter (the invariant)


def test_oracle_2_window_sets_selection_is_bitwise_filter() -> None:
    """`only_days=D` returns exactly the `D` entries of the unfiltered call.

    Bitwise on the scenario paths, not approximate: the training draws are the input
    to every downstream solve, so a differing draw is a differing experiment. This is
    what fails under the pre-R2.7 sequential RNG, where a window's draws depend on how
    many windows preceded it in the series.
    """
    prices = synthetic_day_ahead(days=60, seed=3)
    full = window_sets(prices, history_days=28, n_scenarios=30, seed=0)
    assert len(full) > 10

    picked = [full[i][0] for i in (0, 3, 4, 9, len(full) - 1)]
    subset = window_sets(
        prices, history_days=28, n_scenarios=30, seed=0, only_days=pd.DatetimeIndex(picked)
    )

    assert [w[0] for w in subset] == picked
    by_start = {w[0]: w for w in full}
    for start, train, evaluation in subset:
        ref_start, ref_train, ref_eval = by_start[start]
        assert start == ref_start
        np.testing.assert_array_equal(train.paths, ref_train.paths)
        np.testing.assert_array_equal(train.probs, ref_train.probs)
        np.testing.assert_array_equal(evaluation.paths, ref_eval.paths)


def test_oracle_2b_window_result_does_not_depend_on_the_span_it_sits_in() -> None:
    """The same delivery day scored from a short and a long series is the same window.

    The R2.7 defect in one line. A window's training set is the 28 days before it, so
    a day's scenario draws are fully determined by `(seed, that day)`; any dependence
    on the enclosing series is an artifact of the generator, not of the protocol.
    """
    long_prices = synthetic_day_ahead(days=90, seed=5)
    short_prices = long_prices.loc[long_prices.index[24 * 20] :]

    day = pd.DatetimeIndex(short_prices.index).normalize()[0] + pd.Timedelta(days=28)
    pick = pd.DatetimeIndex([day])

    ((_, long_train, long_eval),) = window_sets(long_prices, seed=0, only_days=pick)
    ((_, short_train, short_eval),) = window_sets(short_prices, seed=0, only_days=pick)

    np.testing.assert_array_equal(long_train.paths, short_train.paths)
    np.testing.assert_array_equal(long_eval.paths, short_eval.paths)


def test_oracle_3_vss_selection_is_a_filter() -> None:
    """`vss_across_windows(only_days=D)` equals the `D`-subset of the full run.

    The same invariant one level up, where it is what makes a fold-selected VSS
    distribution comparable to the swept one the project published before.
    """
    prices = synthetic_day_ahead(days=50, seed=7)
    full = vss_across_windows(prices, _BATT, history_days=28, n_scenarios=30, rho=0.5, seed=0)
    assert len(full) > 8

    picked = pd.DatetimeIndex([full[i].window_start for i in (1, 2, 6)])
    subset = vss_across_windows(
        prices, _BATT, history_days=28, n_scenarios=30, rho=0.5, seed=0, only_days=picked
    )

    by_start = {w.window_start: w for w in full}
    assert [w.window_start for w in subset] == list(picked)
    for w in subset:
        ref = by_start[w.window_start]
        assert w.rp_oos == pytest.approx(ref.rp_oos, abs=TOL)
        assert w.eev_oos == pytest.approx(ref.eev_oos, abs=TOL)
        assert w.vss_oos == pytest.approx(ref.vss_oos, abs=TOL)


# ------------------------------------------------------------------- summaries


def test_oracle_4_summarize_by_block_hand_computed() -> None:
    """12 values in 4 blocks of 3: median, quartiles and share positive by hand.

    values sorted: [-4, -3, -2, -1, 0, 1, 2, 3, 4, 5, 6, 7]; the median is the mean of
    the 6th and 7th (1 and 2) = 1.5. Seven of twelve are strictly positive. Zero is not
    positive, which is the boundary worth pinning: `share_positive` counts `> 0`, so a
    window that exactly breaks even does not count as a win.
    """
    values = np.array([-4.0, -3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
    blocks = np.repeat([0, 1, 2, 3], 3)

    s = summarize_by_block(values, blocks, n_boot=200, seed=0)

    assert s.n_windows == 12
    assert s.median == pytest.approx(1.5, abs=TOL)
    assert s.q25 == pytest.approx(np.percentile(values, 25), abs=TOL)
    assert s.q75 == pytest.approx(np.percentile(values, 75), abs=TOL)
    assert s.share_positive == pytest.approx(7 / 12, abs=TOL)


def test_oracle_5_identical_blocks_give_a_degenerate_interval() -> None:
    """With every block identical, resampling blocks cannot move the median.

    The bootstrap must add no width where the data carries no between-block variation.
    A CI that widens here would be measuring the resampler, not the data.
    """
    block = [1.0, 2.0, 3.0]
    values = np.array(block * 5)
    blocks = np.repeat(np.arange(5), 3)

    s = summarize_by_block(values, blocks, n_boot=500, seed=0)

    assert s.median == pytest.approx(2.0, abs=TOL)
    assert s.median_ci[0] == pytest.approx(2.0, abs=TOL)
    assert s.median_ci[1] == pytest.approx(2.0, abs=TOL)


def test_oracle_6_summarize_by_year_partitions_windows() -> None:
    """Windows split by calendar year, none lost and none counted twice.

    The per-year table is this phase's actual finding, so the partition is pinned
    rather than assumed: a window landing in the wrong year would silently move a
    regime's median.
    """
    starts = list(pd.date_range("2023-12-29", periods=7, freq="D", tz="UTC"))
    values = np.arange(7, dtype=float)

    by_year = summarize_by_year(values, starts)

    assert sorted(by_year) == [2023, 2024]
    assert by_year[2023].n_windows == 3
    assert by_year[2024].n_windows == 4
    assert sum(s.n_windows for s in by_year.values()) == len(values)
    # 2023 holds values 0,1,2 and 2024 holds 3,4,5,6.
    assert by_year[2023].median == pytest.approx(1.0, abs=TOL)
    assert by_year[2024].median == pytest.approx(4.5, abs=TOL)
