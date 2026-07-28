"""Golden oracles for the R2.1e normalized target and its rolling baseline.

Spec: ``docs/specs/R2.1e-target-normalization.md`` § "Golden oracles". The transform
is exact arithmetic, so these are hand-derived rather than statistical: a baseline
window with a known mean and standard deviation must produce exactly those numbers,
and the affine inversion ``price = level + scale * z`` must round-trip to floating
point.

Oracle 4 is the load-bearing one. The coverage guarantee survives normalization only
because the inversion is a *known, strictly increasing* affine map, so an interval in
standardized space carries over point for point. If the inversion were ever wrong or
non-monotone, the conformal argument in the spec would be false and every coverage
number the phase reports would be meaningless.

Pure pandas/numpy: no LightGBM or MAPIE, so these run in the CI tier.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bess.forecaster.features import invert_standardized, rolling_baseline


def _hours(n: int, start: str = "2024-01-01") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="h", tz="UTC")


def test_oracle1_baseline_reproduces_a_known_mean_and_standard_deviation():
    """A 168-hour window of known composition yields exactly its mean and std.

    The series is built so exactly one target's window is a balanced set of 50 +/- 10,
    whose population mean is 50.0 and population standard deviation is exactly 10.0.
    Anything else means the window bounds are off by one or the estimator is using a
    different denominator than the spec says.

    The window spans the 168 hours ending **at** `t - 24 h` inclusive, so the target
    whose window is exactly `prices[0..167]` sits at index 191, not 192: position 191
    of the shifted series covers shifted positions 24..191, which are raw prices
    0..167. Pinning that off-by-one is half the point of this oracle.
    """
    idx = _hours(400)
    values = np.empty(400)
    values[:] = 50.0
    # First 168 hours alternate +/-10 about 50: mean 50, population std 10.
    values[:168] = 50.0 + np.where(np.arange(168) % 2 == 0, 10.0, -10.0)
    prices = pd.Series(values, index=idx, name="price_eur_mwh")

    base = rolling_baseline(prices, window_h=168, gap_h=24, scale_floor=1.0)

    t = idx[191]
    assert base.loc[t, "level"] == 50.0
    assert base.loc[t, "scale"] == 10.0


def test_oracle2_the_leakage_gap_holds_and_the_window_reaches_exactly_that_far():
    """Baseline at `t` ignores everything after `t - 24 h`, and uses `t - 24 h` itself.

    The leakage-safety argument for the normalized target is that `level` and `scale`
    are known at gate closure: for a target on day `D` the window reads nothing newer
    than the same hour on `D-1`, which the auction has already published. That is the
    same bound `lag_24` already uses.

    Both halves matter. The first assertion is the safety property. The second is what
    keeps it honest: a baseline built from a window ending far earlier would also pass
    the first check while quietly discarding a week of information, so the test also
    pins that the window really does reach `t - 24 h`.
    """
    idx = _hours(400)
    prices = pd.Series(np.linspace(10.0, 90.0, 400), index=idx, name="price_eur_mwh")
    base = rolling_baseline(prices, window_h=168, gap_h=24)
    t = idx[300]

    # Safety: nothing strictly after t - 24 h can move the baseline.
    later = prices.copy()
    later[later.index > t - pd.Timedelta(hours=24)] += 500.0
    base_later = rolling_baseline(later, window_h=168, gap_h=24)
    assert base.loc[t, "level"] == base_later.loc[t, "level"]
    assert base.loc[t, "scale"] == base_later.loc[t, "scale"]

    # Non-vacuity: the price exactly at t - 24 h is inside the window, so it must.
    edge = prices.copy()
    edge[edge.index == t - pd.Timedelta(hours=24)] += 500.0
    base_edge = rolling_baseline(edge, window_h=168, gap_h=24)
    assert base.loc[t, "level"] != base_edge.loc[t, "level"]


def test_oracle3_a_flat_window_takes_the_scale_floor():
    """Zero variance must produce the floor, never zero: the inverse must stay finite.

    A constant stretch is not hypothetical on this data. R2.1d measured runs of
    identical prices in real NL history (a 5-hour run at exactly 64.00, and 0.00 runs
    up to 8 hours), so an unfloored scale would divide by zero on real input.
    """
    idx = _hours(400)
    prices = pd.Series(np.full(400, 42.0), index=idx, name="price_eur_mwh")

    base = rolling_baseline(prices, window_h=168, gap_h=24, scale_floor=1.0)

    warmed = base.dropna()
    assert len(warmed) > 0
    assert (warmed["scale"] == 1.0).all()
    assert (warmed["level"] == 42.0).all()
    assert np.isfinite(warmed.to_numpy()).all()


def test_oracle4_affine_inversion_is_exact_and_order_preserving():
    """`price = level + scale * z`, to floating point, on every bound.

    This is the arithmetic the spec's coverage argument rests on: the map is known at
    prediction time and strictly increasing, so an interval covering `z` covers the
    corresponding price exactly as often.
    """
    idx = _hours(4)
    base = pd.DataFrame(
        {"level": [50.0, 0.0, -20.0, 100.0], "scale": [10.0, 1.0, 5.0, 2.5]}, index=idx
    )
    lo = pd.Series([-1.0, -2.0, 0.0, -0.5], index=idx)
    point = pd.Series([0.0, -1.0, 0.5, 0.0], index=idx)
    hi = pd.Series([1.5, 0.0, 2.0, 0.5], index=idx)

    out_lo = invert_standardized(lo, base)
    out_point = invert_standardized(point, base)
    out_hi = invert_standardized(hi, base)

    assert list(out_lo) == [40.0, -2.0, -20.0, 98.75]
    assert list(out_point) == [50.0, -1.0, -17.5, 100.0]
    assert list(out_hi) == [65.0, 0.0, -10.0, 101.25]
    # Strictly increasing map ⇒ ordering survives, which is what the guarantee needs.
    assert (out_lo <= out_point).all() and (out_point <= out_hi).all()


def test_oracle5_negative_prices_survive_the_round_trip():
    """Additive de-levelling must handle prices at or below zero exactly.

    R2.1d measured up to 5.2 percent of hours per year at or below zero, with a
    minimum of -500 EUR/MWh, which is why the spec forbids a log or ratio transform.
    A round trip through standardize-then-invert must be the identity there too.
    """
    idx = _hours(4)
    base = pd.DataFrame({"level": [10.0] * 4, "scale": [20.0] * 4}, index=idx)
    prices = pd.Series([-500.0, -0.01, 0.0, 250.0], index=idx)

    z = (prices - base["level"]) / base["scale"]
    round_trip = invert_standardized(z, base)

    np.testing.assert_allclose(round_trip.to_numpy(), prices.to_numpy(), rtol=0, atol=1e-12)
