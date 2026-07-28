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


@pytest.mark.parametrize("method", ["cqr", "split"])
@pytest.mark.parametrize("seed", [0, 1, 3, 9, 10, 11, 15, 16, 18, 20, 26])
def test_interval_ordering(method, seed):
    """`lower <= point <= upper` at every target, swept over seeds.

    This assertion was in the R2.1 spec and in `formulation-uncertainty.md` §R2.1 from the
    start, but the test behind it ran a **single** seed and passed by luck. Measured
    2026-07-28: on 10 of 30 synthetic seeds the shipped CQR model put the median
    outside its own interval (12 `lower > point` and 9 `point > upper` points), because
    CQR's three quantile models are fit independently and only the lower/upper pair is
    conformalized. The seeds listed here are exactly the ones that exhibited it, so
    this test is red against the pre-fix model rather than merely wider.

    `lower > upper` never occurred, so the interval always carried its conformal
    guarantee and no coverage result was affected; the fix clips the point into the
    interval and leaves the interval untouched.
    """
    prices = synthetic_day_ahead(days=60, seed=seed)
    fc = PriceForecaster(method=method, **_FAST).fit(prices).predict_interval(prices)

    assert (fc.lower <= fc.point).all(), f"{method}/seed {seed}: point below its lower bound"
    assert (fc.point <= fc.upper).all(), f"{method}/seed {seed}: point above its upper bound"
    assert (fc.lower <= fc.upper).all(), f"{method}/seed {seed}: interval inverted"


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


# ------------------------------- recalibration --------------------------------
#
# `recalibrate` is the documented response to interval drift (`forecaster/drift.py`:
# "intervals under-cover: recalibrate, don't retrain"). It had no test at all, and
# under the installed MAPIE it raised `conformalize method already called` for both
# methods, so that drift response was unreachable. These pin the contract it is
# supposed to satisfy: it runs, it refreshes the interval, and it leaves the base
# learners alone.


@pytest.mark.parametrize("method", ["cqr", "split"])
def test_recalibrate_runs_and_predicts(method):
    prices = synthetic_day_ahead(days=120, seed=21)
    train, recent, test = prices[: 70 * 24], prices[70 * 24 : 100 * 24], prices[100 * 24 :]

    fc = PriceForecaster(confidence_level=0.9, method=method, **_FAST).fit(train)
    returned = fc.recalibrate(recent)

    assert returned is fc  # chainable, like fit
    out = fc.predict_interval(test)
    assert (out.lower <= out.point + 1e-9).all()
    assert (out.point <= out.upper + 1e-9).all()
    assert out.width.mean() > 0.0


@pytest.mark.parametrize("method", ["cqr", "split"])
def test_recalibrate_leaves_the_base_models_untouched(method):
    """Only the conformal step moves: the point path must be bit-identical after.

    This is the whole distinction between recalibrating and retraining, and it is
    what makes recalibration the cheap drift response. If the point forecast shifts,
    the base learners were refit and the method is misnamed.
    """
    prices = synthetic_day_ahead(days=120, seed=22)
    train, recent, test = prices[: 70 * 24], prices[70 * 24 : 100 * 24], prices[100 * 24 :]

    fc = PriceForecaster(confidence_level=0.9, method=method, **_FAST).fit(train)
    before = fc.predict_interval(test)
    fc.recalibrate(recent)
    after = fc.predict_interval(test)

    pd.testing.assert_series_equal(before.point, after.point)


def test_recalibrate_actually_changes_the_interval():
    """Non-vacuity: a recalibration on a differently-scaled window must move the band.

    Without this, a `recalibrate` that silently did nothing would satisfy every other
    assertion here (the point path is *required* to be unchanged, so that check alone
    cannot tell a working refresh from a no-op).
    """
    prices = synthetic_day_ahead(days=120, seed=23)
    train, recent, test = prices[: 70 * 24], prices[70 * 24 : 100 * 24], prices[100 * 24 :]

    fc = PriceForecaster(confidence_level=0.9, method="cqr", **_FAST).fit(train)
    before = fc.predict_interval(test).width.mean()
    # A far more volatile recent window ⇒ larger conformal residuals ⇒ wider band.
    fc.recalibrate((recent - recent.mean()) * 4.0 + recent.mean())
    after = fc.predict_interval(test).width.mean()

    assert after > before * 1.1, f"interval barely moved: {before:.3f} → {after:.3f}"


def test_recalibrate_before_fit_is_an_error():
    prices = synthetic_day_ahead(days=40, seed=24)
    with pytest.raises(RuntimeError, match="fit"):
        PriceForecaster(method="cqr", **_FAST).recalibrate(prices)


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


# --- R2.1e: normalized target -------------------------------------------------


def test_normalize_target_off_is_identical_to_r21d():
    """The opt-in identity: `normalize_target=False` cannot move the shipped model.

    Spec oracle 5. This is the un-fakeable anchor that R2.1e changed nothing for
    existing callers; every other gate in the phase is statistical.
    """
    prices = synthetic_day_ahead(days=60, seed=5)

    before = PriceForecaster(**_FAST).fit(prices).predict_interval(prices)
    after = (
        PriceForecaster(normalize_target=False, season_encoding="month", **_FAST)
        .fit(prices)
        .predict_interval(prices)
    )

    pd.testing.assert_series_equal(before.point, after.point)
    pd.testing.assert_series_equal(before.lower, after.lower)
    pd.testing.assert_series_equal(before.upper, after.upper)


@pytest.mark.parametrize("method", ["cqr", "split"])
def test_normalized_forecast_returns_prices_in_order(method):
    """With normalization on, output is still price-space and still ordered.

    The interval is produced in standardized space and inverted, so this checks the
    inversion actually ran: bounds must straddle realistic price magnitudes rather
    than sitting near zero, and `lower <= point <= upper` must survive the transform.
    """
    prices = synthetic_day_ahead(days=60, seed=6)

    fc = (
        PriceForecaster(method=method, normalize_target=True, rolling_stats=True, **_FAST)
        .fit(prices)
        .predict_interval(prices)
    )

    assert (fc.lower <= fc.point).all()
    assert (fc.point <= fc.upper).all()
    assert (fc.width > 0).all()
    # Inverted back to price space: the point path must live near the realized level,
    # which a forecast left in standardized units (mean ~0) would not.
    assert abs(fc.point.mean() - prices.loc[fc.point.index].mean()) < 0.5 * prices.std()


def test_normalization_changes_the_forecast():
    """Non-vacuity: the flag must actually reach the model.

    Without this, a plumbing bug that dropped `normalize_target` on the floor would
    leave every other R2.1e test passing, since they would all be measuring the R2.1d
    model twice.
    """
    prices = synthetic_day_ahead(days=60, seed=7)

    plain = PriceForecaster(**_FAST).fit(prices).predict_interval(prices)
    normed = PriceForecaster(normalize_target=True, **_FAST).fit(prices).predict_interval(prices)

    shared = plain.point.index.intersection(normed.point.index)
    assert len(shared) > 0
    assert not np.allclose(plain.point.loc[shared], normed.point.loc[shared])
