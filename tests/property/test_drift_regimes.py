"""Property gates for the R2.1g synthetic drift regimes.

Spec: ``docs/specs/drift-robust-conformal.md``, Decisions ("knobs selected on
synthetic drift").

These generators are not test scaffolding, they are **the instrument the shipped knob
values are chosen on**, so they get gated like one. Two things have to hold or the
selection means nothing:

- each regime moves the thing it claims to move and leaves the rest alone, so
  attributing a knob's behaviour to "drift in the level" or "drift in the spread" is a
  statement about the data rather than a label on it;
- the whole family is seeded and reproducible, so a chosen half-life can be re-derived
  later rather than taken on faith.

Pure pandas/numpy: no LightGBM or MAPIE, so these run in the CI tier.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bess.data.fixtures import (
    DRIFT_REGIMES,
    synthetic_day_ahead,
    synthetic_drift,
    validate_utc_index,
)


def _daily_level(prices: pd.Series) -> np.ndarray:
    return prices.to_numpy(dtype=float).reshape(-1, 24).mean(axis=1)


def _daily_spread(prices: pd.Series) -> np.ndarray:
    day = prices.to_numpy(dtype=float).reshape(-1, 24)
    return day.max(axis=1) - day.min(axis=1)


@pytest.mark.parametrize("regime", DRIFT_REGIMES)
def test_every_regime_satisfies_the_house_index_schema(regime):
    """Whatever the drift, the output is still a valid internal price series."""
    prices = synthetic_drift(regime=regime, days=60, strength=1.0)

    validate_utc_index(pd.DatetimeIndex(prices.index), source=regime)
    assert prices.name == "price_eur_mwh"
    assert len(prices) == 60 * 24
    assert np.isfinite(prices.to_numpy()).all()


def test_calm_is_the_untouched_control():
    """``"calm"`` is `synthetic_day_ahead` bitwise, at any strength.

    The control has to be the *same* series the rest of the suite uses, or "costs
    nothing on calm data" would be a claim about a different generator. Strength is
    ignored here by construction, and that is asserted rather than assumed.
    """
    base = synthetic_day_ahead(days=90, seed=11)

    pd.testing.assert_series_equal(synthetic_drift(regime="calm", days=90, seed=11), base)
    pd.testing.assert_series_equal(
        synthetic_drift(regime="calm", days=90, seed=11, strength=5.0), base
    )


def test_the_ramp_moves_the_level_monotonically_and_leaves_the_shape_alone():
    """A level climb, not a reshuffle: last-decile level is up, relative spread is not.

    A multiplicative ramp scales spread along with level, so the invariant that
    separates it from a volatility regime is the **ratio**: spread over level holds
    while level climbs.
    """
    r = synthetic_drift(regime="ramp", days=200, strength=2.0)

    level, spread = _daily_level(r), _daily_spread(r)
    assert level[-20:].mean() > 2.0 * level[:20].mean()

    ratio = spread / level
    assert ratio[-20:].mean() == pytest.approx(ratio[:20].mean(), rel=0.25)


def test_the_changepoint_is_flat_either_side_and_steps_where_asked():
    """Nothing drifts before or after; one jump at ``at``.

    This is the regime Barber et al.'s ``rho ** k`` corollary is stated for, so the
    break has to be a genuine step rather than a fast ramp: measured coverage is read
    against a bound that assumes exactly this shape.
    """
    days, at, strength = 200, 0.5, 1.0
    c = synthetic_drift(regime="changepoint", days=days, strength=strength, at=at)
    base = synthetic_day_ahead(days=days, seed=11)

    cut = int(days * 24 * at) // 24
    np.testing.assert_allclose(_daily_level(c)[:cut], _daily_level(base)[:cut])
    np.testing.assert_allclose(_daily_level(c)[cut:], _daily_level(base)[cut:] * (1.0 + strength))


def test_the_volatility_regime_moves_the_spread_and_holds_the_level():
    """Second-moment drift only: the arm-separating case.

    Weighting recalibrates against scores that have grown, so it should help here. A
    level correction has no level to correct. If this regime moved the level too, that
    distinction would be untestable and the phase could not attribute what it measures.
    """
    v = synthetic_drift(regime="volatility", days=200, strength=2.0)
    base = synthetic_day_ahead(days=200, seed=11)

    np.testing.assert_allclose(_daily_level(v), _daily_level(base), atol=1e-9)
    assert _daily_spread(v)[-20:].mean() > 2.0 * _daily_spread(base)[-20:].mean()


@settings(max_examples=30, deadline=None)
@given(
    regime=st.sampled_from(DRIFT_REGIMES),
    seed=st.integers(min_value=0, max_value=50),
    strength=st.floats(min_value=0.0, max_value=3.0),
)
def test_the_generators_are_reproducible(regime, seed, strength):
    """Same arguments, same series. The knob values rest on this."""
    a = synthetic_drift(regime=regime, days=40, seed=seed, strength=strength)
    b = synthetic_drift(regime=regime, days=40, seed=seed, strength=strength)

    pd.testing.assert_series_equal(a, b)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"regime": "nope"},
        {"regime": "ramp", "strength": -1.0},
        {"regime": "changepoint", "at": 0.0},
        {"regime": "changepoint", "at": 1.0},
    ],
)
def test_out_of_contract_arguments_are_refused(kwargs):
    """A misspelled regime is a `ValueError`, not a silently calm series.

    The failure that would be worst here is the quiet one: selecting knobs against a
    series that was supposed to drift and did not, then shipping the result.
    """
    with pytest.raises(ValueError):
        synthetic_drift(days=30, **kwargs)
