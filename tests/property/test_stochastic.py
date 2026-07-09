"""Property invariants for R2.3: risk-aware two-stage dispatch + MPC recourse.

These are structural guarantees the formulation §R2.3 promises for *any* valid
scenario set:
- VSS ≥ 0 and EVPI ≥ 0, with the ordering EEV ≤ RP ≤ WS (extends R1.4);
- every scenario's recourse stays within the budget of the shared (non-
  anticipative) day-ahead commitment;
- the mean-CVaR frontier is monotone and the risk term reduces downside;
- the receding-horizon (MPC) recourse never underperforms a static commitment.

MILP solves are not cheap, so the solve-heavy invariants run over a small fixed
set of seeds (deterministic, bounded runtime) rather than a Hypothesis sweep.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bess.assets.battery import BatterySpec
from bess.optimizer.core import solve
from bess.recourse import rolling_recourse
from bess.scenarios import ScenarioSet
from bess.stochastic import (
    out_of_sample_vss,
    solve_stochastic,
    value_of_stochastic_solution,
)

TOL = 1e-6


def _scen(paths: np.ndarray, probs: np.ndarray) -> ScenarioSet:
    idx = pd.date_range("2026-01-01", periods=paths.shape[1], freq="h", tz="UTC")
    return ScenarioSet(paths=np.asarray(paths, float), probs=np.asarray(probs, float), index=idx)


def _rand_probs(rng: np.random.Generator, s: int) -> np.ndarray:
    raw = rng.random(s) + 0.05
    return raw / raw.sum()


_BATT = BatterySpec(capacity=2.0, soc_initial=0.5, soc_terminal=0.5)


# ------------------------------------------------ VSS >= 0 and the value ordering


@pytest.mark.parametrize("seed", range(5))
def test_vss_nonneg_and_value_ordering(seed: int) -> None:
    rng = np.random.default_rng(seed)
    paths = rng.uniform(0.0, 60.0, size=(3, 3))
    scen = _scen(paths, _rand_probs(rng, 3))
    res = value_of_stochastic_solution(scen, _BATT, rho=0.4)
    assert res.vss >= -TOL
    assert res.evpi >= -TOL
    assert res.eev <= res.rp + TOL
    assert res.rp <= res.ws + TOL


# ------------------------------------- out-of-sample VSS (the honest gate, 0021)


def _gen_days(rng: np.random.Generator, n: int, horizon: int = 4) -> np.ndarray:
    """Days that share a cheap charge hour (t0) but peak at a *random* later hour.

    A single day-ahead commitment can bank the common cheap charge; the peak hour
    is what recourse must adapt to, so the stochastic plan generalises out-of-sample
    where the mean-committed discharge hour does not.
    """
    days = []
    for _ in range(n):
        p = rng.uniform(8.0, 12.0, size=horizon)
        p[0] = rng.uniform(3.0, 6.0)
        p[rng.integers(1, horizon)] = rng.uniform(45.0, 60.0)
        days.append(p)
    return np.asarray(days)


@pytest.mark.parametrize("seed", range(3))
def test_out_of_sample_vss_positive(seed: int) -> None:
    rng = np.random.default_rng(seed)
    train = _scen(_gen_days(rng, 40), np.full(40, 1 / 40))
    evaluation = _scen(_gen_days(rng, 40), np.full(40, 1 / 40))  # disjoint draw
    res = out_of_sample_vss(train, evaluation, _BATT, rho=0.4)
    # The RP commitment, fit on training, beats the mean commitment on held-out days.
    assert res.vss_oos > 0.3


# -------------------------------- non-anticipativity: recourse within the budget


def test_recourse_within_budget_of_commitment() -> None:
    scen = _scen(np.array([[5.0, 50.0, 10.0, 10.0], [5.0, 10.0, 50.0, 10.0]]), np.array([0.5, 0.5]))
    rho = 0.4
    sched = solve_stochastic(scen, _BATT, rho=rho)
    p_rated = max(_BATT.p_charge_max, _BATT.p_discharge_max)
    assert len(sched.g_da) == scen.horizon
    assert len(sched.recourse) == scen.n_scenarios
    for s in range(scen.n_scenarios):
        for t in range(scen.horizon):
            assert abs(sched.recourse[s][t] - sched.g_da[t]) <= rho * p_rated + 1e-6


# --------------------------------- frontier monotonicity + risk reduces downside


def test_frontier_monotone_and_risk_reduces_downside() -> None:
    # Asymmetric scenarios (a big-spread day, a flat day, an early-expensive day)
    # with a tight budget: the shared commitment must compromise, so the risk term
    # genuinely bends the decision rather than passing trivially on a symmetric set.
    scen = _scen(
        np.array([[10.0, 70.0, 10.0, 10.0], [10.0, 10.0, 10.0, 10.0], [60.0, 10.0, 10.0, 10.0]]),
        np.array([0.5, 0.25, 0.25]),
    )
    neutral = solve_stochastic(scen, _BATT, alpha=0.8, lambda_=0.0, rho=0.25)
    mid = solve_stochastic(scen, _BATT, alpha=0.8, lambda_=0.5, rho=0.25)
    averse = solve_stochastic(scen, _BATT, alpha=0.8, lambda_=0.95, rho=0.25)
    # Expected profit is non-increasing as risk weight grows (you pay for safety).
    assert mid.expected_profit <= neutral.expected_profit + TOL
    assert averse.expected_profit <= mid.expected_profit + TOL
    # The risk term does real work: the averse solution strictly trades expected
    # profit for a strictly smaller loss-CVaR (reduced downside).
    assert averse.expected_profit < neutral.expected_profit - 1e-3
    assert averse.cvar < neutral.cvar - 1e-3


# ------------------------------------------- MPC recourse >= static commitment


def test_rolling_recourse_beats_static_commit() -> None:
    realized = np.array([10.0, 50.0, 20.0, 40.0, 15.0, 30.0])
    forecast = np.full(realized.shape, 25.0)  # deliberately flat / imperfect
    roll = rolling_recourse(realized, _BATT, forecast=forecast)
    # Static: plan once on the forecast, execute the plan against realized prices.
    static = solve(list(forecast), _BATT)
    static_val = sum(
        realized[t] * (static.p_discharge[t] - static.p_charge[t]) for t in range(len(realized))
    )
    assert roll.value >= static_val - 1e-6


def test_rolling_recourse_perfect_foresight_matches_optimum() -> None:
    """With a perfect forecast the MPC policy realises the perfect-foresight value."""
    realized = np.array([10.0, 50.0, 20.0, 40.0])
    roll = rolling_recourse(realized, _BATT)  # forecast=None ⇒ perfect foresight
    opt = solve(list(realized), _BATT).objective
    assert roll.value == pytest.approx(opt, abs=1e-5)


# ---------------------------------------------------------------- determinism


def test_solve_stochastic_deterministic() -> None:
    scen = _scen(np.array([[10.0, 50.0, 20.0], [20.0, 40.0, 10.0]]), np.array([0.5, 0.5]))
    a = solve_stochastic(scen, _BATT, rho=0.5).objective
    b = solve_stochastic(scen, _BATT, rho=0.5).objective
    assert a == pytest.approx(b, abs=1e-9)
