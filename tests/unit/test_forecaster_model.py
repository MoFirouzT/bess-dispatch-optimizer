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

from bess.data.fixtures import synthetic_day_ahead  # noqa: E402
from bess.forecaster import PriceForecaster, walk_forward_coverage  # noqa: E402

_FAST = dict(n_estimators=60, random_state=0)


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
