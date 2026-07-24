"""Model + coverage gates for the forecaster (R2.1).

Skip-guarded: these need the ``forecast`` dependency group (LightGBM + MAPIE). The
statistical anchor is the **coverage gate** — empirical coverage on data the model
did not calibrate on, under walk-forward, must land in ``0.9 ± 0.05`` — plus a
fixed-seed **reproducibility** gate standing in for a hand-solved oracle.
"""

from __future__ import annotations

import pytest

pytest.importorskip("lightgbm")
pytest.importorskip("mapie")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from bess.data.fixtures import synthetic_day_ahead  # noqa: E402
from bess.forecaster import PriceForecaster, walk_forward_coverage  # noqa: E402

_FAST = dict(n_estimators=60, random_state=0)


def _synthetic_fundamentals(prices: pd.Series, *, seed: int = 0) -> pd.DataFrame:
    """A residual-load-shaped fundamentals frame on the price index (day-ahead MW)."""
    rng = np.random.default_rng(seed)
    idx = prices.index
    hour = idx.hour.to_numpy()
    solar = np.clip(np.sin((hour - 6) / 12 * np.pi), 0, None) * 4000 + rng.normal(0, 200, len(idx))
    wind = rng.uniform(500, 6000, len(idx))
    load = 12000 + 3000 * np.sin((hour - 8) / 24 * 2 * np.pi) + rng.normal(0, 300, len(idx))
    return pd.DataFrame(
        {"load_da": load, "wind_da": wind, "solar_da": np.clip(solar, 0, None)}, index=idx
    )


def test_interval_ordering():
    prices = synthetic_day_ahead(days=90, seed=5)
    train, test = prices[: 70 * 24], prices[70 * 24 :]
    fc = PriceForecaster(confidence_level=0.9, method="cqr", **_FAST).fit(train)
    out = fc.predict_interval(test)
    assert (out.lower <= out.point + 1e-9).all()
    assert (out.point <= out.upper + 1e-9).all()


def test_wider_interval_at_higher_confidence():
    prices = synthetic_day_ahead(days=90, seed=6)
    train, test = prices[: 70 * 24], prices[70 * 24 :]
    narrow = (
        PriceForecaster(confidence_level=0.8, method="cqr", **_FAST)
        .fit(train)
        .predict_interval(test)
    )
    wide = (
        PriceForecaster(confidence_level=0.95, method="cqr", **_FAST)
        .fit(train)
        .predict_interval(test)
    )
    # Higher confidence ⇒ no-narrower intervals (nested coverage).
    assert wide.width.mean() >= narrow.width.mean()


@pytest.mark.parametrize("method", ["cqr", "split"])
def test_coverage_gate_within_tolerance(method):
    prices = synthetic_day_ahead(days=170, seed=7)
    coverage, width = walk_forward_coverage(
        prices, confidence_level=0.9, method=method, n_folds=3, test_days=5, **_FAST
    )
    assert 0.85 <= coverage <= 0.95, f"{method}: coverage {coverage:.3f} outside [0.85, 0.95]"
    assert width > 0.0


def test_reproducible_with_fixed_seed():
    prices = synthetic_day_ahead(days=80, seed=8)
    train, test = prices[: 60 * 24], prices[60 * 24 :]
    a = PriceForecaster(confidence_level=0.9, method="cqr", random_state=0, n_estimators=60).fit(
        train
    )
    b = PriceForecaster(confidence_level=0.9, method="cqr", random_state=0, n_estimators=60).fit(
        train
    )
    import pandas as pd

    pd.testing.assert_series_equal(a.predict_interval(test).lower, b.predict_interval(test).lower)
    pd.testing.assert_series_equal(a.predict_interval(test).upper, b.predict_interval(test).upper)


# ----------------------------- R2.1c fundamentals -----------------------------


def test_use_fundamentals_off_is_identical_to_r21():
    """use_fundamentals=False ignores any fundamentals ⇒ byte-identical to the R2.1 model."""
    prices = synthetic_day_ahead(days=80, seed=11)
    train, test = prices[: 60 * 24], prices[60 * 24 :]
    fund = _synthetic_fundamentals(prices, seed=11)

    base = PriceForecaster(method="cqr", **_FAST).fit(train)
    off = PriceForecaster(method="cqr", use_fundamentals=False, **_FAST).fit(
        train, fundamentals=fund.loc[train.index]
    )
    pd.testing.assert_series_equal(
        base.predict_interval(test).point, off.predict_interval(test).point
    )


def test_fundamentals_reach_the_model_and_change_the_forecast():
    """With use_fundamentals=True, supplying fundamentals changes the fitted forecast."""
    prices = synthetic_day_ahead(days=80, seed=12)
    train, test = prices[: 60 * 24], prices[60 * 24 :]
    fund = _synthetic_fundamentals(prices, seed=12)

    without = PriceForecaster(method="cqr", **_FAST).fit(train)
    with_fund = PriceForecaster(method="cqr", use_fundamentals=True, **_FAST).fit(
        train, fundamentals=fund.loc[train.index]
    )
    p0 = without.predict_interval(test)
    p1 = with_fund.predict_interval(test, fundamentals=fund.loc[test.index])
    # The extra features actually flow through: the point path is not identical.
    assert not np.allclose(p0.point.to_numpy(), p1.point.to_numpy())
    # And the interval is still well-formed.
    assert (p1.lower <= p1.point + 1e-9).all() and (p1.point <= p1.upper + 1e-9).all()


def test_graceful_fallback_when_fundamentals_missing(caplog):
    """use_fundamentals=True but none supplied ⇒ valid R2.1-equivalent forecast + warning."""
    prices = synthetic_day_ahead(days=80, seed=13)
    train, test = prices[: 60 * 24], prices[60 * 24 :]

    base = PriceForecaster(method="cqr", **_FAST).fit(train)
    with caplog.at_level("WARNING"):
        degraded = PriceForecaster(method="cqr", use_fundamentals=True, **_FAST).fit(train)
    assert any("falling back" in r.message for r in caplog.records)
    # Fell back to price+calendar, so it matches the plain R2.1 model exactly.
    pd.testing.assert_series_equal(
        base.predict_interval(test).point, degraded.predict_interval(test).point
    )
