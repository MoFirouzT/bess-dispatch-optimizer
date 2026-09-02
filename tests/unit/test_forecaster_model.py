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

    Spec oracle 5. This is the anchor that cannot be faked, that R2.1e changed nothing for
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


# --- R2.1g: the weighted conformal path ---------------------------------------


def test_oracle1_weighting_off_is_bit_identical_to_the_shipped_model():
    """The opt-in identity: `weight_half_life_days=None` cannot move R2.1e's model.

    Spec: `docs/specs/drift-robust-conformal.md` golden oracle 1. `fit` now always
    computes calibration scores (the ACI arm needs them), so this is the gate that the
    extra work is inert: with weighting off, MAPIE still owns the margin and every
    series is bitwise what it was.
    """
    prices = synthetic_day_ahead(days=120, seed=3)

    before = PriceForecaster(**_FAST).fit(prices).predict_interval(prices)
    after = (
        PriceForecaster(weight_half_life_days=None, **_FAST).fit(prices).predict_interval(prices)
    )

    pd.testing.assert_series_equal(before.point, after.point)
    pd.testing.assert_series_equal(before.lower, after.lower)
    pd.testing.assert_series_equal(before.upper, after.upper)


@pytest.mark.parametrize("method", ["cqr", "split"])
def test_oracle1b_our_unweighted_margin_reproduces_mapies_symmetric_interval(method):
    """At rho = 1 our own conformal step *is* MAPIE's symmetric correction, bitwise.

    This is the load-bearing half of oracle 1 and the reason MAPIE keeps the shipped
    path (spec Decisions). The weighted construction must contain the unweighted one
    exactly rather than approximate it, otherwise every comparison in R2.1g is
    confounded by an implementation difference instead of measuring the method.

    **`symmetric_correction=True` is not a convenience here, it is the construction.**
    `formulation-uncertainty.md` §R2.1 defines one signed score with one margin
    `s_hat`, applied to both bounds, and that is also the form Barber et al.'s Theorem
    2a is stated for. MAPIE's *default* is `symmetric_correction=False`, a different
    (also valid) variant with a separate constant per side, which is what the shipped
    model runs and what the docstring below records as a defect found by this test.
    """
    prices = synthetic_day_ahead(days=120, seed=5)
    fc = PriceForecaster(method=method, confidence_level=0.9, **_FAST).fit(prices)

    feats = fc._features(prices, None, None)
    x = feats.to_numpy()
    # `symmetric_correction` is a CQR-only knob: split conformal has one construction,
    # `mu_hat +/- s_hat`, which is already the symmetric form.
    kwargs = {"symmetric_correction": True} if method == "cqr" else {}
    _, symmetric = fc._mapie.predict_interval(x, **kwargs)
    ours = fc.predict_interval(prices, alpha=0.1)

    np.testing.assert_allclose(ours.lower.to_numpy(), symmetric[:, 0, 0], atol=1e-12)
    np.testing.assert_allclose(ours.upper.to_numpy(), symmetric[:, 1, 0], atol=1e-12)


def test_the_shipped_default_is_the_asymmetric_variant_not_the_documented_one():
    """A defect this phase found: the code and `formulation-uncertainty.md` §R2.1 disagree.

    §R2.1 defines CQR with a single margin `s_hat` added to both bounds. MAPIE's
    `predict_interval` defaults to `symmetric_correction=False`, which fits a separate
    constant per side, so the shipped forecaster has never run the construction the
    canonical math file describes.

    **No coverage number is wrong.** Both are valid conformal constructions with the
    same marginal guarantee, which is why nothing caught this for four phases: every
    coverage gate passed either way. What is wrong is that the single source of truth
    does not describe what executes, and CLAUDE.md §1 says that gets surfaced rather
    than quietly reconciled.

    This test pins the divergence so it cannot be lost while the human decides which
    side moves. It fails, correctly, on the day the code and the doc are brought into
    line, and the fix then is to delete it rather than to loosen it.
    """
    prices = synthetic_day_ahead(days=120, seed=5)
    fc = PriceForecaster(method="cqr", confidence_level=0.9, **_FAST).fit(prices)

    shipped = fc.predict_interval(prices)  # MAPIE default: asymmetric
    documented = fc.predict_interval(prices, alpha=0.1)  # §R2.1 as written: symmetric

    assert not np.allclose(shipped.lower.to_numpy(), documented.lower.to_numpy())
    # The asymmetric variant is the narrower of the two here, so the divergence is not
    # conservative: it is not the case that the shipped model merely over-covers.
    assert float(shipped.width.mean()) < float(documented.width.mean())


def test_a_short_half_life_moves_the_margin_and_keeps_the_interval_ordered():
    """Weighting is not inert, and it is not monotone in width either.

    The non-vacuity check: coverage alone cannot tell a working decay from a knob that
    does nothing, so something must show the margin actually moved.

    It deliberately does **not** assert the interval widens. A shorter half-life
    concentrates mass on recent scores, and whether that is wider depends on whether
    recent scores are larger, which is a property of the data rather than of the
    construction. The monotone claim that does hold is gated in
    `tests/property/test_drift_robust_conformal.py`, on a rising score path where the
    direction is determined.
    """
    prices = synthetic_day_ahead(days=200, seed=7)

    fast = PriceForecaster(weight_half_life_days=3.0, **_FAST).fit(prices)
    slow = PriceForecaster(weight_half_life_days=None, **_FAST).fit(prices)

    f = fast.predict_interval(prices)
    s = slow.predict_interval(prices)

    assert abs(float(f.width.mean()) - float(s.width.mean())) > 0.5
    assert (f.lower <= f.upper).all()
