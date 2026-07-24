"""Golden feature-alignment oracles for R2.1c exogenous fundamentals.

Feature construction is exact arithmetic (no MILP, no learner), so these are
un-fakeable like R2.1's leakage checks, not statistical. They pin: the
residual-load arithmetic, the opt-in identity (fundamentals off ⇒ exactly R2.1),
and the CONTEMPORANEOUS alignment of the day-ahead forecast features to the
target ``t`` (not lagged like price). Spec: ``docs/specs/R2.1c-exogenous-fundamentals.md``.

Pure pandas: runs without the ``forecast`` dependency group.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bess.data.fixtures import synthetic_day_ahead
from bess.forecaster import DEFAULT_LAGS, make_features


def _hours(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2024-06-01", periods=n, freq="1h", tz="UTC")


def _fundamentals(idx: pd.DatetimeIndex, load, wind, solar) -> pd.DataFrame:
    return pd.DataFrame({"load_da": load, "wind_da": wind, "solar_da": solar}, index=idx)


def test_oracle1_residual_load_arithmetic_and_components():
    """residual_load = load_da − wind_da − solar_da, exactly; components pass through."""
    idx = _hours(2)
    prices = pd.Series([40.0, 55.0], index=idx, name="price_eur_mwh")
    fund = _fundamentals(idx, load=[100.0, 120.0], wind=[30.0, 10.0], solar=[20.0, 0.0])

    feats = make_features(prices, lags=(), calendar=False, fundamentals=fund)

    assert list(feats["residual_load"]) == [50.0, 110.0]
    assert list(feats["load_da"]) == [100.0, 120.0]
    assert list(feats["wind_da"]) == [30.0, 10.0]
    assert list(feats["solar_da"]) == [20.0, 0.0]


def test_oracle3_opt_in_identity_none_equals_r21():
    """fundamentals=None ⇒ byte-identical to the R2.1 feature matrix."""
    prices = synthetic_day_ahead(days=20, seed=7)
    base = make_features(prices, lags=DEFAULT_LAGS, calendar=True)
    with_none = make_features(prices, lags=DEFAULT_LAGS, calendar=True, fundamentals=None)
    pd.testing.assert_frame_equal(base, with_none)


def test_oracle4_contemporaneous_alignment_not_lagged():
    """The fundamentals feature at target t reads the forecast row at t, not t−1."""
    idx = _hours(3)
    prices = pd.Series([40.0, 55.0, 33.0], index=idx, name="price_eur_mwh")
    # Distinct per-row values so a one-step misalignment would be visible.
    fund = _fundamentals(
        idx, load=[100.0, 200.0, 300.0], wind=[0.0, 0.0, 0.0], solar=[0.0, 0.0, 0.0]
    )

    feats = make_features(prices, lags=(), calendar=False, fundamentals=fund)

    # residual_load at t equals load_da at t (contemporaneous), not the previous hour.
    assert feats.loc[idx[1], "residual_load"] == 200.0
    assert feats.loc[idx[2], "residual_load"] == 300.0


def test_oracle2_leakage_future_fundamentals_do_not_touch_past_features():
    """Mutating fundamentals at/after t+1 leaves the feature row at t unchanged.

    The R2.1c analogue of the price no-leakage guard: contemporaneous alignment
    means a target's fundamentals feature reads only its own row, never a later
    (eventually-realized) one, so no look-ahead can enter.
    """
    idx = _hours(6)
    prices = pd.Series(np.arange(6, dtype=float), index=idx, name="price_eur_mwh")
    fund = _fundamentals(
        idx, load=[10, 20, 30, 40, 50, 60], wind=[1, 2, 3, 4, 5, 6], solar=[0, 0, 0, 0, 0, 0]
    )
    before = make_features(prices, lags=(1,), calendar=False, fundamentals=fund)

    target = idx[2]
    row_before = before.loc[target].copy()

    mutated = fund.copy()
    mutated.loc[mutated.index >= idx[3]] += 999.0  # perturb the future only
    after = make_features(prices, lags=(1,), calendar=False, fundamentals=mutated)

    pd.testing.assert_series_equal(row_before, after.loc[target])
