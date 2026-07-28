"""Property gates for R2.1d fold placement and the day-block coverage bootstrap.

Spec: ``docs/specs/R2.1d-evaluation-honesty.md`` § "Property tests". The load-bearing
invariants are that no fold can train on data at or after the block it tests, that
folds never overlap (which would pool the same test day into coverage twice), and
that the bootstrap actually resamples **whole days** rather than individual hours.
That last one is the un-fakeable check here: a resampler that quietly ignored the
day blocking would satisfy every other property in this file while reporting an
interval several times too narrow, which is exactly the defect this phase exists to
remove.

Pure pandas/numpy: no LightGBM or MAPIE, so these run in the CI tier.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bess.forecaster.evaluate import coverage_ci, rolling_origin_folds


def _days(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2021-01-01", periods=n, freq="D", tz="UTC")


@settings(max_examples=50, deadline=None)
@given(
    n_days=st.integers(min_value=200, max_value=2000),
    n_folds=st.integers(min_value=1, max_value=20),
    test_days=st.integers(min_value=1, max_value=7),
    train_days=st.one_of(st.none(), st.integers(min_value=30, max_value=120)),
)
def test_no_fold_trains_on_or_after_the_block_it_tests(n_days, n_folds, test_days, train_days):
    """The no-leakage invariant, for every fold the generator will ever emit."""
    days = _days(n_days)
    try:
        folds = rolling_origin_folds(
            days, n_folds=n_folds, test_days=test_days, train_days=train_days
        )
    except ValueError:
        return  # a request the span cannot host is refused, which is its own gate

    for f in folds:
        assert f.train_start < f.train_end
        # train_end is the exclusive upper bound of training, so it may equal the
        # first test day but never exceed it: training data is strictly earlier.
        assert f.train_end <= f.test_start
        assert f.test_start <= f.test_end


@settings(max_examples=50, deadline=None)
@given(
    n_days=st.integers(min_value=200, max_value=2000),
    n_folds=st.integers(min_value=2, max_value=20),
    test_days=st.integers(min_value=1, max_value=7),
)
def test_test_blocks_are_disjoint_ordered_and_equal_length(n_days, n_folds, test_days):
    days = _days(n_days)
    try:
        folds = rolling_origin_folds(days, n_folds=n_folds, test_days=test_days, train_days=90)
    except ValueError:
        return

    assert len(folds) == n_folds
    for f in folds:
        assert (f.test_end - f.test_start).days == test_days - 1
    for earlier, later in zip(folds, folds[1:], strict=False):
        assert earlier.test_end < later.test_start  # strictly disjoint, strictly ordered


@settings(max_examples=50, deadline=None)
@given(
    n_days=st.integers(min_value=300, max_value=2000),
    n_folds=st.integers(min_value=1, max_value=15),
    train_days=st.integers(min_value=30, max_value=200),
)
def test_a_fixed_training_window_is_never_silently_short(n_days, n_folds, train_days):
    """With `train_days` set every fold gets exactly that much history, or it raises.

    A short first fold would make fold-to-fold results incomparable while looking
    fine, which is the confound this phase replaces the expanding window to avoid.
    """
    days = _days(n_days)
    try:
        folds = rolling_origin_folds(days, n_folds=n_folds, test_days=5, train_days=train_days)
    except ValueError:
        return

    for f in folds:
        assert (f.train_end - f.train_start).days == train_days


@settings(max_examples=30, deadline=None)
@given(n_days=st.integers(min_value=100, max_value=1500))
def test_r21_defaults_reproduce_the_historical_block_placement(n_days):
    """Backward compatibility as arithmetic: the R2.1 harness's own fold formula.

    R2.1 computed `start = len(days) - n_folds*test_days + fold*test_days` and trained
    on everything strictly earlier. Pinning it here is what keeps the historical R2.1
    coverage number reproducible after the harness is rewritten.
    """
    days = _days(n_days)
    n_folds, test_days = 3, 5
    folds = rolling_origin_folds(
        days, n_folds=n_folds, test_days=test_days, train_days=None, spacing="contiguous"
    )

    total_test = n_folds * test_days
    for i, f in enumerate(folds):
        start = len(days) - total_test + i * test_days
        assert f.test_start == days[start]
        assert f.test_end == days[start + test_days - 1]
        assert f.train_start == days[0]  # expanding
        assert f.train_end == days[start]


@settings(max_examples=20, deadline=None)
@given(
    n_days=st.integers(min_value=40, max_value=200),
    p=st.floats(min_value=0.6, max_value=0.99),
    seed=st.integers(min_value=0, max_value=50),
)
def test_bootstrap_interval_is_well_formed_and_deterministic(n_days, p, seed):
    rng = np.random.default_rng(seed)
    per_day = [rng.random(24) < p for _ in range(n_days)]

    lo, hi = coverage_ci(per_day, level=0.95, n_boot=500, seed=0)
    lo2, hi2 = coverage_ci(per_day, level=0.95, n_boot=500, seed=0)

    pooled = float(np.concatenate(per_day).mean())
    assert lo <= pooled <= hi
    assert 0.0 <= lo <= hi <= 1.0
    assert (lo, hi) == (lo2, hi2)  # fixed seed ⇒ bit-stable


def test_interval_narrows_as_test_days_grow():
    """More evaluated days ⇒ a tighter interval. The reason to add folds at all."""
    rng = np.random.default_rng(0)
    small = [rng.random(24) < 0.9 for _ in range(20)]
    large = [rng.random(24) < 0.9 for _ in range(400)]

    lo_s, hi_s = coverage_ci(small, level=0.95, n_boot=1000, seed=0)
    lo_l, hi_l = coverage_ci(large, level=0.95, n_boot=1000, seed=0)

    assert (hi_l - lo_l) < (hi_s - lo_s)


def test_day_block_resampling_really_blocks():
    """The un-fakeable one: blocking must widen the interval versus resampling hours.

    Two datasets with the *same* pooled coverage of 0.5 over 100 days. In the first the
    indicator is constant within a day (perfect intra-day correlation, the realistic
    case: a bad day misses roughly 24 in a row); in the second the same successes are
    spread evenly so every day is mixed. A correct day-block bootstrap reports a much
    wider interval for the first, because its effective sample is 100 days rather than
    2400 hours. A resampler that ignored the blocking would report near-identical
    intervals and would pass every other property in this file.
    """
    clustered = [
        np.ones(24, dtype=bool) if i % 2 == 0 else np.zeros(24, dtype=bool) for i in range(100)
    ]
    mixed = [np.array([h % 2 == 0 for h in range(24)]) for _ in range(100)]

    assert float(np.concatenate(clustered).mean()) == 0.5
    assert float(np.concatenate(mixed).mean()) == 0.5

    lo_c, hi_c = coverage_ci(clustered, level=0.95, n_boot=2000, seed=0)
    lo_m, hi_m = coverage_ci(mixed, level=0.95, n_boot=2000, seed=0)

    # Every day of `mixed` is identical, so resampling days cannot move the estimate.
    assert (hi_m - lo_m) == pytest.approx(0.0, abs=1e-12)
    # The clustered case carries real day-to-day variation and must show it.
    assert (hi_c - lo_c) > 0.15
