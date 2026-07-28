"""Property gates for the R2.1e normalized target, features, and season encoding.

Spec: ``docs/specs/R2.1e-target-normalization.md`` § "Property tests".

Two of these carry most of the weight. **Opt-in identity** is the un-fakeable anchor
that nothing else moved: with normalization off, the feature matrix must be
byte-identical to R2.1d's, so the phase cannot silently change the shipped model.
**Width scales with recent volatility** is the non-vacuity check: coverage being
unchanged cannot distinguish a working transform from an inert one, so something has
to show the transform is actually doing its job.

Pure pandas/numpy: no LightGBM or MAPIE, so these run in the CI tier.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from bess.data.fixtures import synthetic_day_ahead
from bess.forecaster.features import (
    DEFAULT_LAGS,
    invert_standardized,
    make_features,
    rolling_baseline,
)


@settings(max_examples=25, deadline=None)
@given(days=st.integers(min_value=30, max_value=90), seed=st.integers(min_value=0, max_value=40))
def test_opt_in_identity_leaves_the_r21d_feature_matrix_untouched(days, seed):
    """`normalize=None` and `season_encoding="month"` reproduce R2.1d exactly."""
    prices = synthetic_day_ahead(days=days, seed=seed)

    before = make_features(prices, lags=DEFAULT_LAGS, calendar=True)
    after = make_features(
        prices,
        lags=DEFAULT_LAGS,
        calendar=True,
        normalize=None,
        season_encoding="month",
        rolling_stats=False,
    )

    pd.testing.assert_frame_equal(before, after)


@settings(max_examples=25, deadline=None)
@given(days=st.integers(min_value=30, max_value=90), seed=st.integers(min_value=0, max_value=40))
def test_no_leakage_survives_normalization(days, seed):
    """Normalized features at `t` still depend only on prices strictly before `t`.

    Normalization divides by a statistic of the price series, so it is exactly the
    kind of change that can reintroduce look-ahead without anyone noticing. Mutating
    the target day and everything after it must leave that day's feature row alone.
    """
    prices = synthetic_day_ahead(days=days, seed=seed)
    base = rolling_baseline(prices)
    feats = make_features(prices, normalize=base, season_encoding="cyclical", rolling_stats=True)
    if feats.empty:
        return

    target_day = feats.index.normalize().unique()[-1]
    before = feats[feats.index.normalize() == target_day].copy()

    mutated = prices.copy()
    mutated[mutated.index.normalize() >= target_day] += 999.0
    base_after = rolling_baseline(mutated)
    after = make_features(
        mutated, normalize=base_after, season_encoding="cyclical", rolling_stats=True
    )
    after = after[after.index.normalize() == target_day]

    pd.testing.assert_frame_equal(before, after)


@settings(max_examples=30, deadline=None)
@given(days=st.integers(min_value=20, max_value=80), seed=st.integers(min_value=0, max_value=40))
def test_scale_is_strictly_positive_everywhere(days, seed):
    prices = synthetic_day_ahead(days=days, seed=seed)
    base = rolling_baseline(prices).dropna()
    assert (base["scale"] > 0).all()


def test_scale_is_positive_on_constant_and_negative_series():
    """The two inputs most likely to break a divisor, checked explicitly."""
    idx = pd.date_range("2024-01-01", periods=400, freq="h", tz="UTC")
    for values in (np.full(400, 0.0), np.full(400, -50.0), np.linspace(-200.0, -1.0, 400)):
        base = rolling_baseline(pd.Series(values, index=idx)).dropna()
        assert (base["scale"] > 0).all()
        assert np.isfinite(base.to_numpy()).all()


@settings(max_examples=25, deadline=None)
@given(days=st.integers(min_value=30, max_value=80), seed=st.integers(min_value=0, max_value=40))
def test_standardize_then_invert_is_the_identity(days, seed):
    """The round trip that makes the inherited-coverage argument testable.

    If this holds, an interval covering the standardized target covers the price
    exactly as often, which is the whole content of the spec's affine-map claim.
    """
    prices = synthetic_day_ahead(days=days, seed=seed)
    base = rolling_baseline(prices).dropna()
    aligned = prices.loc[base.index]

    z = (aligned - base["level"]) / base["scale"]
    round_trip = invert_standardized(z, base)

    np.testing.assert_allclose(round_trip.to_numpy(), aligned.to_numpy(), rtol=0.0, atol=1e-9)


@settings(max_examples=25, deadline=None)
@given(days=st.integers(min_value=30, max_value=80), seed=st.integers(min_value=0, max_value=40))
def test_inversion_preserves_interval_ordering(days, seed):
    """`lower <= point <= upper` survives the transform, floor included."""
    prices = synthetic_day_ahead(days=days, seed=seed)
    base = rolling_baseline(prices).dropna()
    idx = base.index

    lo = pd.Series(np.full(len(idx), -1.5), index=idx)
    point = pd.Series(np.zeros(len(idx)), index=idx)
    hi = pd.Series(np.full(len(idx), 1.5), index=idx)

    out_lo = invert_standardized(lo, base)
    out_point = invert_standardized(point, base)
    out_hi = invert_standardized(hi, base)

    assert (out_lo <= out_point).all()
    assert (out_point <= out_hi).all()


def test_width_scales_with_recent_volatility():
    """Non-vacuity: a more volatile trailing window must not give a narrower interval.

    Two series with the same level, one twice as volatile. A fixed standardized
    half-width inverts to a price-space width proportional to `scale`, so the volatile
    series must come back strictly wider. Without this, an inert transform (one that
    returned a constant scale) would satisfy every other property here.
    """
    idx = pd.date_range("2024-01-01", periods=600, freq="h", tz="UTC")
    rng = np.random.default_rng(0)
    noise = rng.normal(0.0, 1.0, 600)

    calm = pd.Series(50.0 + 5.0 * noise, index=idx)
    volatile = pd.Series(50.0 + 10.0 * noise, index=idx)

    base_calm = rolling_baseline(calm).dropna()
    base_vol = rolling_baseline(volatile).dropna()

    half = pd.Series(1.0, index=base_calm.index)
    width_calm = invert_standardized(half, base_calm) - invert_standardized(-half, base_calm)
    half_v = pd.Series(1.0, index=base_vol.index)
    width_vol = invert_standardized(half_v, base_vol) - invert_standardized(-half_v, base_vol)

    assert width_vol.mean() > 1.5 * width_calm.mean()


def test_cyclical_encoding_is_in_range_and_continuous_across_new_year():
    """The defect `month` has, and the reason the encoding is worth re-applying.

    Day-of-year sine and cosine stay inside [-1, 1] and move continuously from
    31 December to 1 January, where the plain month number jumps 12 -> 1. R2.1
    reverted this encoding because a 4-month window left it out of range; with
    R2.1d's 365-day training window that precondition is met.
    """
    idx = pd.date_range("2023-12-25", periods=24 * 14, freq="h", tz="UTC")
    prices = pd.Series(np.linspace(20.0, 80.0, len(idx)), index=idx)

    feats = make_features(prices, lags=(24,), calendar=True, season_encoding="cyclical")

    assert "doy_sin" in feats.columns and "doy_cos" in feats.columns
    assert "month" not in feats.columns
    assert feats[["doy_sin", "doy_cos"]].abs().max().max() <= 1.0

    daily = feats[["doy_sin", "doy_cos"]].resample("1D").first().dropna()
    steps = np.linalg.norm(np.diff(daily.to_numpy(), axis=0), axis=1)
    # One day of movement on the unit circle is about 2*pi/365 ≈ 0.0172; no jump.
    assert steps.max() < 0.05
