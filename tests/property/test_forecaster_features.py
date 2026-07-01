"""Feature-construction gates for the forecaster (R2.1) — the no-leakage invariant.

Pure pandas: these run without the ``forecast`` dependency group. The load-bearing
check is that a feature row for a target day depends only on *prior-day* prices, so
mutating that day's (and later) prices cannot change it — the un-fakeable leakage
guard, the forecasting counterpart to the backtest's gate C.
"""

from __future__ import annotations

import pandas as pd

from bess.data.fixtures import synthetic_day_ahead
from bess.forecaster import DEFAULT_LAGS, make_features


def test_no_leakage_features_depend_only_on_prior_days():
    prices = synthetic_day_ahead(days=30, seed=3)
    feats = make_features(prices, lags=(24, 48), calendar=True)

    days = feats.index.normalize().unique()
    target_day = days[15]
    before = feats[feats.index.normalize() == target_day].copy()

    # Mutate every price on the target day and all later days.
    mutated = prices.copy()
    mutated[mutated.index.normalize() >= target_day] += 999.0
    feats_after = make_features(mutated, lags=(24, 48), calendar=True)
    after = feats_after[feats_after.index.normalize() == target_day]

    # Features for the target day are unchanged: they read only days ≤ target_day − 1.
    pd.testing.assert_frame_equal(before, after)


def test_features_are_well_formed():
    prices = synthetic_day_ahead(days=20, seed=1)
    feats = make_features(prices, lags=DEFAULT_LAGS, calendar=True)

    # Warm-up rows (first max(lag) hours) dropped; no NaNs remain.
    assert not feats.isna().any().any()
    assert feats.index.isin(prices.index).all()
    assert len(feats) == len(prices) - max(DEFAULT_LAGS)
    # Every lag column present, and all lags are prior-day (≥ 24 h) — no same-day leak.
    for lag in DEFAULT_LAGS:
        assert f"lag_{lag}" in feats.columns
    assert min(DEFAULT_LAGS) >= 24


def test_lag_columns_equal_the_shifted_price():
    prices = synthetic_day_ahead(days=10, seed=2)
    feats = make_features(prices, lags=(24,), calendar=False)
    # lag_24 at t must equal the price 24 h earlier, exactly.
    expected = prices.shift(24).loc[feats.index]
    pd.testing.assert_series_equal(feats["lag_24"], expected, check_names=False)
