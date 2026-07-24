"""Property + loader-contract gates for R2.1c exogenous fundamentals.

Two correctness anchors, both token-free:

- **make_features fundamentals path** — residual-load identity, no-look-ahead
  (leakage) invariance, opt-in identity, and no spurious NaNs.
- **loader contract** — ``fetch_load_forecast`` / ``fetch_renewable_forecast``
  call the *day-ahead forecast* ENTSO-E endpoints, never the realized-actuals
  ones (the forecast-not-actual rule that makes contemporaneous alignment
  leakage-safe), and normalize the real 15-min shape to the internal hourly
  UTC schema. The ENTSO-E client is monkeypatched, so no token is needed.

Spec: ``docs/specs/R2.1c-exogenous-fundamentals.md``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bess.data.fixtures import synthetic_day_ahead
from bess.forecaster import DEFAULT_LAGS, make_features


def _hours(n: int, tz: str = "UTC") -> pd.DatetimeIndex:
    return pd.date_range("2024-06-01", periods=n, freq="1h", tz=tz)


def _rand_fund(idx: pd.DatetimeIndex, rng: np.random.Generator) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "load_da": rng.uniform(8000, 18000, len(idx)),
            "wind_da": rng.uniform(0, 6000, len(idx)),
            "solar_da": rng.uniform(0, 5000, len(idx)),
        },
        index=idx,
    )


# ----------------------------- make_features -----------------------------


@settings(max_examples=40, deadline=None)
@given(seed=st.integers(0, 2**16))
def test_residual_load_identity(seed: int):
    rng = np.random.default_rng(seed)
    idx = _hours(6)
    prices = pd.Series(rng.uniform(-50, 200, 6), index=idx, name="price_eur_mwh")
    fund = _rand_fund(idx, rng)
    feats = make_features(prices, lags=(1,), calendar=False, fundamentals=fund)
    expected = (fund["load_da"] - fund["wind_da"] - fund["solar_da"]).loc[feats.index]
    pd.testing.assert_series_equal(feats["residual_load"], expected, check_names=False)


@settings(max_examples=30, deadline=None)
@given(seed=st.integers(0, 2**16))
def test_leakage_future_fundamentals_do_not_touch_past(seed: int):
    rng = np.random.default_rng(seed)
    idx = _hours(8)
    prices = pd.Series(rng.uniform(-50, 200, 8), index=idx, name="price_eur_mwh")
    fund = _rand_fund(idx, rng)
    feats = make_features(prices, lags=(1, 2), calendar=True, fundamentals=fund)

    cut = idx[4]
    past = feats[feats.index < cut].copy()
    mutated = fund.copy()
    mutated.loc[mutated.index >= cut] += 5000.0
    feats2 = make_features(prices, lags=(1, 2), calendar=True, fundamentals=mutated)
    pd.testing.assert_frame_equal(past, feats2[feats2.index < cut])


def test_opt_in_identity_across_seeds():
    for seed in range(5):
        prices = synthetic_day_ahead(days=15, seed=seed)
        base = make_features(prices, lags=DEFAULT_LAGS, calendar=True)
        again = make_features(prices, lags=DEFAULT_LAGS, calendar=True, fundamentals=None)
        pd.testing.assert_frame_equal(base, again)


def test_no_new_nans_beyond_lag_warmup():
    prices = synthetic_day_ahead(days=10, seed=2)
    idx = prices.index
    rng = np.random.default_rng(0)
    fund = _rand_fund(idx, rng)
    feats = make_features(prices, lags=(24, 48), calendar=True, fundamentals=fund)
    assert not feats.isna().any().any()
    # Fundamentals cover the whole index, so warm-up is still governed by the lags only.
    assert len(feats) == len(prices) - 48


def test_partial_components_no_residual_but_columns_pass_through():
    """With only some components present, residual_load is not fabricated."""
    idx = _hours(4)
    prices = pd.Series([1.0, 2.0, 3.0, 4.0], index=idx, name="price_eur_mwh")
    fund = pd.DataFrame({"load_da": [10.0, 11.0, 12.0, 13.0]}, index=idx)
    feats = make_features(prices, lags=(), calendar=False, fundamentals=fund)
    assert "load_da" in feats.columns
    assert "residual_load" not in feats.columns


# ------------------------------ loader contract ------------------------------


class _FakeClient:
    """Records which ENTSO-E endpoints are called and returns realistic shapes."""

    def __init__(self, api_key: str) -> None:
        self.calls: list[str] = []

    def _idx15(self, start, end):
        # entsoe-py returns zone-local (Amsterdam) 15-min data; start/end are already
        # tz-aware, so let date_range infer the tz rather than passing a conflicting one.
        start = start.tz_convert("Europe/Amsterdam")
        end = end.tz_convert("Europe/Amsterdam")
        return pd.date_range(start, end, freq="15min", inclusive="left")

    def query_load_forecast(self, zone, start, end):
        self.calls.append("query_load_forecast")
        idx = self._idx15(start, end)
        return pd.DataFrame({"Forecasted Load": np.linspace(10000, 12000, len(idx))}, index=idx)

    def query_wind_and_solar_forecast(self, zone, start, end):
        self.calls.append("query_wind_and_solar_forecast")
        idx = self._idx15(start, end)
        return pd.DataFrame(
            {
                "Solar": np.linspace(0, 3000, len(idx)),
                "Wind Offshore": np.linspace(1000, 1200, len(idx)),
                "Wind Onshore": np.linspace(2000, 1800, len(idx)),
            },
            index=idx,
        )

    def query_load(self, *a, **k):  # realized actuals — must never be called here
        self.calls.append("query_load")
        raise AssertionError("forecast loaders must not call the realized-actuals endpoint")


@pytest.fixture()
def fake_entsoe(monkeypatch):
    import bess.data.entsoe as mod

    created: dict[str, _FakeClient] = {}

    def factory(api_key):
        c = _FakeClient(api_key)
        created["client"] = c
        return c

    monkeypatch.setattr(mod, "EntsoePandasClient", factory)
    monkeypatch.setenv("ENTSOE_API_TOKEN", "dummy-token")
    return created


def _window():
    return pd.Timestamp("2024-06-01", tz="Europe/Brussels"), pd.Timestamp(
        "2024-06-02", tz="Europe/Brussels"
    )


def test_load_forecast_calls_forecast_endpoint_and_normalizes(fake_entsoe):
    from bess.data.entsoe import fetch_load_forecast

    start, end = _window()
    s = fetch_load_forecast("NL", start, end)

    assert fake_entsoe["client"].calls == ["query_load_forecast"]  # forecast, not actual
    assert s.name == "load_da"
    assert str(s.index.tz) == "UTC"
    # Normalized to the internal hourly grid (15-min mean-resampled).
    steps = set(s.index.to_series().diff().dropna())
    assert steps == {pd.Timedelta("1h")}


def test_renewable_forecast_sums_wind_and_maps_columns(fake_entsoe):
    from bess.data.entsoe import fetch_renewable_forecast

    start, end = _window()
    df = fetch_renewable_forecast("NL", start, end)

    assert fake_entsoe["client"].calls == ["query_wind_and_solar_forecast"]
    assert list(df.columns) == ["wind_da", "solar_da"]
    assert str(df.index.tz) == "UTC"
    # wind_da is offshore + onshore combined (both fake series are positive).
    assert (df["wind_da"] > 0).all()
    steps = set(df.index.to_series().diff().dropna())
    assert steps == {pd.Timedelta("1h")}
