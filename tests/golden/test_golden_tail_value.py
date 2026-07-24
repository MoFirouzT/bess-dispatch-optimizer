"""Golden oracles for R2.5b: dispatch value of the scenario tail.

Contract: docs/specs/R2.5b-tail-dispatch-value.md § "Golden oracles". The exact
anchors are the tail-off identity (identical sets ⇒ TV = 0) and the bookkeeping /
antisymmetry; the designed spike-capture case pins that the study can detect a real
tail benefit. Token-free (the ML wrapper is exercised by the live integration test).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bess.assets.battery import BatterySpec
from bess.scenarios import ScenarioSet
from bess.stochastic.study import tail_value_from_sets

TOL = 1e-6
_BATT = BatterySpec(capacity=2.0, soc_initial=0.5, soc_terminal=0.5)


def _set(paths: np.ndarray, index: pd.DatetimeIndex) -> ScenarioSet:
    s = paths.shape[0]
    return ScenarioSet(paths=paths, probs=np.full(s, 1.0 / s), index=index)


def _idx(t: int) -> pd.DatetimeIndex:
    return pd.date_range("2024-03-01", periods=t, freq="h", tz="UTC")


def test_oracle1_tail_off_identity_is_zero():
    """Identical plain and tail sets ⇒ same commitment, same score, TV = 0 exactly."""
    idx = _idx(6)
    rng = np.random.default_rng(0)
    paths = rng.uniform(5.0, 40.0, size=(8, 6))
    scen = _set(paths, idx)
    realized = rng.uniform(5.0, 40.0, 6)
    basis = paths.mean(axis=0)

    r = tail_value_from_sets(scen, scen, realized, _BATT, basis=basis, rho=0.5)
    assert r.profit_tail_eur == pytest.approx(r.profit_plain_eur, abs=TOL)
    assert r.tv_eur == pytest.approx(0.0, abs=TOL)


def test_oracle3_bookkeeping_and_antisymmetry():
    """TV = profit_tail − profit_plain, and swapping the two sets negates TV."""
    idx = _idx(6)
    rng = np.random.default_rng(2)
    a = _set(rng.uniform(5.0, 50.0, size=(6, 6)), idx)
    b = _set(rng.uniform(5.0, 50.0, size=(6, 6)), idx)
    realized = rng.uniform(5.0, 50.0, 6)
    basis = rng.uniform(10.0, 30.0, 6)

    ab = tail_value_from_sets(a, b, realized, _BATT, basis=basis, rho=0.5)
    ba = tail_value_from_sets(b, a, realized, _BATT, basis=basis, rho=0.5)

    assert ab.tv_eur == pytest.approx(ab.profit_tail_eur - ab.profit_plain_eur, abs=TOL)
    assert ab.tv_eur == pytest.approx(-ba.tv_eur, abs=TOL)


def test_oracle2_designed_spike_capture_is_positive():
    """A tail set that shows a spike the plain set hides earns more on a realized spike.

    Designed instance: the plain scenarios are flat (no arbitrage signal), the tail
    scenarios carry a discharge-worthy spike at hour 4 with a cheap charge hour at 0,
    and the realized path has that spike. With a moderate recourse budget the tail-aware
    commitment is positioned to capture more of the realized spike than the plain one
    can reach, so TV > 0. (Numbers below were measured on this designed instance.)
    """
    idx = _idx(6)
    flat = np.full(6, 20.0)
    plain = _set(np.tile(flat, (8, 1)), idx)
    # Tail scenarios: cheap at t0, spike at t4.
    spike_day = np.array([5.0, 20.0, 20.0, 20.0, 120.0, 20.0])
    tail = _set(np.tile(spike_day, (8, 1)), idx)
    realized = spike_day.copy()

    # Realized-price settlement (the study convention): the commitment settles at the
    # realized day-ahead price, so anticipating the spike is worth real money.
    r = tail_value_from_sets(tail, plain, realized, _BATT, basis=realized, rho=0.5)
    assert r.tv_eur > TOL
