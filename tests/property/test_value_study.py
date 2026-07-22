"""Property invariants for R2.5: value evaluation hardening (formulation §R2.5).

Contract: docs/specs/R2.5-value-evaluation.md § "Property tests".

- pinball loss: non-negative, zero iff exact, monotone as a uniform shift grows;
- the window study: leakage (early windows are bit-identical when *future* days
  change), bookkeeping (one entry per complete window with enough history,
  incomplete trailing day ignored), determinism under a fixed seed, and the
  in-sample Birge-Louveaux ordering on a window's training set;
- the forecast-value comparison: antisymmetric under swapping its inputs,
  deterministic on repeat.

MILP-backed invariants run on small fixed instances (deterministic, bounded
runtime), matching the R2.3 property-test convention.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from bess.assets.battery import BatterySpec
from bess.forecaster.evaluate import pinball_loss
from bess.stochastic import value_of_stochastic_solution
from bess.stochastic.study import (
    forecast_value_from_sets,
    vss_across_windows,
    window_sets,
)

TOL = 1e-6

_BATT = BatterySpec(capacity=2.0, soc_initial=0.5, soc_terminal=0.5)

_floats = st.floats(min_value=-200.0, max_value=200.0, allow_nan=False, allow_infinity=False)


# ------------------------------------------------------------- pinball loss


@given(
    y=st.lists(_floats, min_size=1, max_size=20),
    tau=st.floats(min_value=0.01, max_value=0.99),
    shift=st.floats(min_value=0.1, max_value=50.0),
)
def test_pinball_nonneg_zero_iff_exact_monotone(y: list[float], tau: float, shift: float) -> None:
    arr = np.asarray(y)
    # Zero iff the prediction is exact.
    assert pinball_loss(arr, arr, tau=tau) == 0.0
    # Non-negative, and strictly growing as a uniform shift moves away from truth.
    near = pinball_loss(arr, arr - shift, tau=tau)
    far = pinball_loss(arr, arr - 2.0 * shift, tau=tau)
    assert near > 0.0
    assert far > near
    # The shifted loss is exactly linear in the shift: τ·c for under-prediction.
    assert near == pytest.approx(tau * shift, rel=1e-9)


@given(y=st.lists(_floats, min_size=1, max_size=20), tau=st.floats(min_value=0.01, max_value=0.99))
def test_pinball_rejects_nothing_valid_and_bounds_tau(y: list[float], tau: float) -> None:
    assert pinball_loss(y, list(reversed(y)), tau=tau) >= 0.0
    with pytest.raises(ValueError):
        pinball_loss(y, y, tau=0.0)
    with pytest.raises(ValueError):
        pinball_loss(y, y, tau=1.0)


# ----------------------------------------------------- window study: leakage


def _random_series(n_days: int, seed: int, extra_hours: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    n = n_days * 24 + extra_hours
    idx = pd.date_range("2024-03-01", periods=n, freq="h", tz="UTC")
    return pd.Series(rng.uniform(0.0, 60.0, size=n), index=idx)


_KW = dict(history_days=4, n_scenarios=4, seed=0)


def test_no_leakage_future_days_cannot_move_earlier_windows() -> None:
    """The functional form of the §R1.4 information set: altering the *last*
    day's prices must leave every earlier window's result bit-identical."""
    prices = _random_series(7, seed=2)
    altered = prices.copy()
    altered.iloc[-24:] = altered.iloc[-24:] + 50.0

    base = vss_across_windows(prices, _BATT, rho=0.4, **_KW)
    moved = vss_across_windows(altered, _BATT, rho=0.4, **_KW)

    assert len(base) == len(moved) == 3
    for a, b in zip(base[:-1], moved[:-1], strict=True):
        assert a.window_start == b.window_start
        assert a.rp_oos == b.rp_oos  # bit-identical, not approx: nothing upstream moved
        assert a.eev_oos == b.eev_oos


# ------------------------------------------- window study: bookkeeping/seed


def test_window_bookkeeping_and_determinism() -> None:
    prices = _random_series(7, seed=3, extra_hours=5)  # trailing partial day
    res = vss_across_windows(prices, _BATT, rho=0.4, **_KW)

    # One entry per complete window with enough history; the partial day is not one.
    assert len(res) == 7 - 4
    starts = [w.window_start for w in res]
    assert starts == sorted(starts)
    assert all(b - a == pd.Timedelta(days=1) for a, b in zip(starts, starts[1:], strict=False))
    for w in res:
        assert w.vss_oos == pytest.approx(w.rp_oos - w.eev_oos, abs=TOL)

    # Deterministic under a fixed seed (bit-identical on repeat).
    again = vss_across_windows(prices, _BATT, rho=0.4, **_KW)
    assert [(w.rp_oos, w.eev_oos) for w in again] == [(w.rp_oos, w.eev_oos) for w in res]


# ------------------------------- window study: in-sample ordering per window


def test_in_sample_ordering_holds_on_window_training_set() -> None:
    """EEV ≤ RP ≤ WS (Birge-Louveaux) on a study window's own training set."""
    prices = _random_series(6, seed=4)
    sets = window_sets(prices, history_days=5, n_scenarios=6, seed=0)
    assert len(sets) == 1
    _, train, _ = sets[0]
    res = value_of_stochastic_solution(train, _BATT, rho=0.4)
    assert res.eev <= res.rp + TOL
    assert res.rp <= res.ws + TOL
    assert res.vss >= -TOL


# --------------------------------------------------- forecast value algebra


def test_forecast_value_antisymmetric_and_deterministic() -> None:
    rng = np.random.default_rng(5)
    idx = pd.date_range("2024-03-01", periods=24, freq="h", tz="UTC")
    from bess.scenarios import ScenarioSet

    a = ScenarioSet(rng.uniform(0.0, 60.0, (5, 24)), np.full(5, 0.2), index=idx)
    b = ScenarioSet(rng.uniform(0.0, 60.0, (5, 24)), np.full(5, 0.2), index=idx)
    realized = rng.uniform(0.0, 60.0, 24)

    ab = forecast_value_from_sets(a, b, realized, _BATT, rho=0.4)
    ba = forecast_value_from_sets(b, a, realized, _BATT, rho=0.4)
    assert ab.fv_eur == pytest.approx(-ba.fv_eur, abs=1e-9)
    assert ab.profit_conformal_eur == pytest.approx(ba.profit_naive_eur, abs=1e-9)

    again = forecast_value_from_sets(a, b, realized, _BATT, rho=0.4)
    assert again.fv_eur == pytest.approx(ab.fv_eur, abs=1e-9)


def test_fv_windows_bookkeeping_and_determinism() -> None:
    """One output per input item, in order; bit-identical on repeat (amendment
    2026-07-22)."""
    from bess.scenarios import ScenarioSet
    from bess.stochastic.study import fv_windows_from_sets

    rng = np.random.default_rng(6)
    idx = pd.date_range("2024-03-01", periods=24, freq="h", tz="UTC")
    items = []
    for d in range(3):
        conf = ScenarioSet(rng.uniform(0.0, 60.0, (4, 24)), np.full(4, 0.25), index=idx)
        naive = ScenarioSet(rng.uniform(0.0, 60.0, (4, 24)), np.full(4, 0.25), index=idx)
        start = pd.Timestamp("2024-03-10", tz="UTC") + pd.Timedelta(days=d)
        items.append((start, conf, naive, rng.uniform(0.0, 60.0, 24)))

    first = fv_windows_from_sets(items, _BATT, rho=0.4)
    second = fv_windows_from_sets(items, _BATT, rho=0.4)

    assert len(first) == len(items)
    assert [w.window_start for w in first] == [i[0] for i in items]
    for w in first:
        assert w.fv_eur == pytest.approx(w.profit_conformal_eur - w.profit_naive_eur, abs=TOL)
    assert [(w.profit_conformal_eur, w.fv_eur) for w in first] == [
        (w.profit_conformal_eur, w.fv_eur) for w in second
    ]
