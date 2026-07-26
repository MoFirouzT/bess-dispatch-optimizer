"""Property invariants for the R2.6 bid-curve value study (formulation-r2 §R2.6).

- the curve read is monotone and agrees with the branch it came from;
- obligation scoring generalizes §R2.5's schedule scoring (they agree wherever both
  apply) and stays well defined where it does not;
- the value is exactly null on a degenerate scenario set, and deterministic;
- the across-windows harness is well formed: strictly-prior training data, one
  result per scoreable window, and a delivery gap reported beside every euro.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bess.assets.battery import BatterySpec
from bess.scenarios import ScenarioSet
from bess.stochastic import (
    bid_curve_value_across_windows,
    bid_curve_value_from_sets,
    curve_response,
    solve_stochastic,
)

TOL = 1e-6

_BATT = BatterySpec(
    capacity=2.0,
    soc_min=0.0,
    soc_initial=0.5,
    soc_terminal=0.5,
    eta_charge=0.9,
    eta_discharge=0.9,
)


def _scen(paths: np.ndarray, probs: np.ndarray) -> ScenarioSet:
    arr = np.asarray(paths, dtype=float)
    idx = pd.date_range("2026-01-01", periods=arr.shape[1], freq="h", tz="UTC")
    return ScenarioSet(paths=arr, probs=np.asarray(probs, dtype=float), index=idx)


def _rand_set(seed: int, s: int = 4, t: int = 4) -> ScenarioSet:
    rng = np.random.default_rng(seed)
    return _scen(rng.uniform(0.0, 60.0, size=(s, t)), np.full(s, 1 / s))


# ------------------------------------------------------------- the curve read


@pytest.mark.parametrize("seed", range(4))
def test_curve_response_is_monotone_in_price(seed: int) -> None:
    scen = _rand_set(seed)
    res = solve_stochastic(scen, _BATT, rho=0.4, bid_curve=True)
    assert res.curve is not None

    rng = np.random.default_rng(seed + 100)
    grid = np.sort(rng.uniform(-20.0, 90.0, size=25))
    for t in range(len(res.curve)):
        answers = [curve_response(res.curve, [p] * len(res.curve))[t] for p in grid]
        assert all(b >= a - TOL for a, b in zip(answers, answers[1:], strict=False))


@pytest.mark.parametrize("seed", range(4))
def test_curve_response_agrees_with_the_branch_on_support(seed: int) -> None:
    scen = _rand_set(seed)
    res = solve_stochastic(scen, _BATT, rho=0.4, bid_curve=True)
    assert res.curve is not None and res.g_da_branches is not None
    for s, path in enumerate(scen.paths):
        assert curve_response(res.curve, path) == pytest.approx(res.g_da_branches[s], abs=TOL)


# --------------------------------------------------------------- the scoring


@pytest.mark.parametrize("seed", range(4))
def test_obligation_scoring_generalizes_schedule_scoring(seed: int) -> None:
    """Where the commitment is a real schedule, the two evaluation paths agree."""
    rng = np.random.default_rng(seed)
    realized = rng.uniform(0.0, 60.0, size=4)
    train = _scen(rng.uniform(0.0, 60.0, size=(4, 4)), np.full(4, 0.25))
    fitted = solve_stochastic(train, _BATT, rho=0.4)  # an R1.1-feasible commitment

    evaluation = _scen(realized[None, :], np.array([1.0]))
    charge = [max(0.0, -g) for g in fitted.g_da]
    discharge = [max(0.0, g) for g in fitted.g_da]

    obligation = solve_stochastic(evaluation, _BATT, rho=0.4, commitment=fitted.g_da)
    schedule = solve_stochastic(
        evaluation, _BATT, rho=0.4, fix_da=(charge, discharge), pi_da=realized
    )
    assert obligation.expected_profit == pytest.approx(schedule.expected_profit, abs=1e-5)


@pytest.mark.parametrize("seed", range(3))
def test_value_is_null_on_a_degenerate_set(seed: int) -> None:
    rng = np.random.default_rng(seed)
    path = rng.uniform(5.0, 80.0, size=4)
    scen = _scen(np.tile(path, (3, 1)), np.full(3, 1 / 3))
    res = bid_curve_value_from_sets(scen, path, _BATT, rho=0.4)
    assert res.bcv_eur == pytest.approx(0.0, abs=TOL)


def test_determinism() -> None:
    scen = _rand_set(2)
    realized = np.random.default_rng(9).uniform(0.0, 60.0, size=4)
    first = bid_curve_value_from_sets(scen, realized, _BATT, rho=0.4)
    second = bid_curve_value_from_sets(scen, realized, _BATT, rho=0.4)
    assert first == second


# ------------------------------------------------------- the window harness


def _price_series(days: int, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    shape = np.array([20, 15, 12, 10, 18, 35, 60, 80, 55, 40, 30, 25] * 2, dtype=float)
    values = np.concatenate([rng.normal(shape, 8.0) for _ in range(days)])
    idx = pd.date_range("2026-01-01", periods=24 * days, freq="h", tz="UTC")
    return pd.Series(values, index=idx, name="price")


def test_across_windows_is_well_formed() -> None:
    """One result per scoreable window, in order, each carrying its delivery gap."""
    prices = _price_series(days=10)
    out = bid_curve_value_across_windows(
        prices, _BATT, history_days=7, n_scenarios=4, rho=0.4, seed=0
    )
    assert len(out) == 3  # 10 days minus the 7-day training block
    assert [w.window_start for w in out] == sorted(w.window_start for w in out)
    for w in out:
        assert w.bcv_eur == pytest.approx(w.profit_curve_eur - w.profit_scalar_eur, abs=1e-5)
        assert w.delivery_gap_curve_mwh >= -TOL
        assert w.delivery_gap_scalar_mwh >= -TOL


def test_across_windows_uses_only_strictly_prior_days() -> None:
    """Perturbing the last day cannot move any earlier window (the leakage boundary)."""
    prices = _price_series(days=10)
    tampered = prices.copy()
    tampered.iloc[-24:] = tampered.iloc[-24:] * 3.0 + 250.0

    base = bid_curve_value_across_windows(
        prices, _BATT, history_days=7, n_scenarios=4, rho=0.4, seed=0
    )
    after = bid_curve_value_across_windows(
        tampered, _BATT, history_days=7, n_scenarios=4, rho=0.4, seed=0
    )
    assert base[:-1] == after[:-1]
