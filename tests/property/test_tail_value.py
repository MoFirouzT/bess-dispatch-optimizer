"""Property invariants for R2.5b: dispatch value of the scenario tail.

Contract: docs/specs/R2.5b-tail-dispatch-value.md § "Property tests". Token-free:
the tail-off identity, antisymmetry, determinism, and the well-formed per-window
distribution. The realized-euro *sign* of TV is a finding, not a gate (reported by
the live integration test), exactly as for the R2.5 forecast value.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bess.assets.battery import BatterySpec
from bess.scenarios import ScenarioSet
from bess.stochastic.study import tail_value_across_windows, tail_value_from_sets

TOL = 1e-6
_BATT = BatterySpec(capacity=2.0, soc_initial=0.5, soc_terminal=0.5)


def _idx(t: int) -> pd.DatetimeIndex:
    return pd.date_range("2024-03-01", periods=t, freq="h", tz="UTC")


def _set(rng: np.random.Generator, s: int, t: int) -> ScenarioSet:
    return ScenarioSet(
        paths=rng.uniform(5.0, 60.0, (s, t)), probs=np.full(s, 1.0 / s), index=_idx(t)
    )


@pytest.mark.parametrize("seed", range(4))
def test_tail_off_identity_is_zero(seed: int):
    rng = np.random.default_rng(seed)
    scen = _set(rng, 6, 6)
    realized = rng.uniform(5.0, 60.0, 6)
    r = tail_value_from_sets(scen, scen, realized, _BATT, basis=realized, rho=0.5)
    assert r.tv_eur == pytest.approx(0.0, abs=TOL)


@pytest.mark.parametrize("seed", range(4))
def test_antisymmetry(seed: int):
    rng = np.random.default_rng(seed + 10)
    a, b = _set(rng, 6, 6), _set(rng, 6, 6)
    realized = rng.uniform(5.0, 60.0, 6)
    ab = tail_value_from_sets(a, b, realized, _BATT, basis=realized, rho=0.5)
    ba = tail_value_from_sets(b, a, realized, _BATT, basis=realized, rho=0.5)
    assert ab.tv_eur == pytest.approx(-ba.tv_eur, abs=TOL)


def test_determinism():
    rng = np.random.default_rng(0)
    a, b = _set(rng, 6, 6), _set(rng, 6, 6)
    realized = rng.uniform(5.0, 60.0, 6)
    r1 = tail_value_from_sets(a, b, realized, _BATT, basis=realized, rho=0.5)
    r2 = tail_value_from_sets(a, b, realized, _BATT, basis=realized, rho=0.5)
    assert r1.tv_eur == r2.tv_eur


def test_across_windows_well_formed():
    """The per-window harness returns one WindowTV per scoreable window, TV = tail − plain."""
    rng = np.random.default_rng(3)
    days = 20
    # A synthetic hourly series with a daily shape plus occasional evening spikes.
    shape = 20 + 10 * np.sin((np.arange(24) - 8) / 24 * 2 * np.pi)
    rows = []
    for _ in range(days):
        p = shape + rng.normal(0, 3, 24)
        if rng.random() < 0.2:
            p[18] += rng.uniform(40, 120)
        rows.append(p)
    prices = pd.Series(
        np.concatenate(rows),
        index=pd.date_range("2024-01-01", periods=days * 24, freq="h", tz="UTC"),
        name="price_eur_mwh",
    )

    windows = tail_value_across_windows(
        prices, _BATT, history_days=10, n_scenarios=12, rho=0.5, seed=0
    )
    assert len(windows) == days - 10
    for w in windows:
        assert w.tv_eur == pytest.approx(w.profit_tail_eur - w.profit_plain_eur, abs=TOL)
