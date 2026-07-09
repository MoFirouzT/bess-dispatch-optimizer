"""Golden oracles for R2.3: risk-aware two-stage dispatch + VSS (formulation §R2.3).

Exact, hand-verifiable cases:
- the CVaR (Rockafellar-Uryasev) linearization arithmetic on a discrete loss set;
- the **VSS = 0 collapse** at the recourse-budget limits (ρ→0 and ρ large): the
  trap reproduced exactly, not papered over;
- reduction to the deterministic R1.1 solve at a single scenario (S = 1).

The strictly-positive VSS case is a *measured* escape (a designed instance where
the mean schedule is a poor central commitment), asserted strictly positive
rather than to a hand value: RP and EEV are full MILP optima, not closed forms.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bess.assets.battery import BatterySpec
from bess.optimizer.core import solve
from bess.scenarios import ScenarioSet
from bess.stochastic import (
    cvar_from_losses,
    value_of_stochastic_solution,
)

TOL = 1e-6


def _scen(paths: list[list[float]] | np.ndarray, probs: list[float]) -> ScenarioSet:
    arr = np.asarray(paths, dtype=float)
    idx = pd.date_range("2026-01-01", periods=arr.shape[1], freq="h", tz="UTC")
    return ScenarioSet(paths=arr, probs=np.asarray(probs, dtype=float), index=idx)


# --------------------------------------------------------------- CVaR arithmetic


def test_cvar_exact_discrete() -> None:
    """CVaR_0.75 of losses [-10,-5,0,20] (equiprobable) is 20, VaR is 0 — by hand.

    The convex PWL objective η + (1/(1-α))·E[(L-η)^+] is minimized at η=0
    (value 20); η=-5 gives 25, η=-10 gives 35. The minimizing η is the VaR.
    """
    losses = [-10.0, -5.0, 0.0, 20.0]
    probs = [0.25, 0.25, 0.25, 0.25]
    cvar, var = cvar_from_losses(losses, probs, alpha=0.75)
    assert cvar == pytest.approx(20.0, abs=TOL)
    assert var == pytest.approx(0.0, abs=TOL)


# ------------------------------------------------------ VSS = 0 collapse (trap)


@pytest.mark.parametrize("rho", [0.0, 3.0])
def test_vss_zero_at_budget_limits(rho: float) -> None:
    """At ρ→0 (no recourse) and ρ large (unlimited recourse) VSS collapses to 0.

    ρ=0: g^(s)=g^DA forced, so RP and EEV both reduce to the mean-value problem.
    ρ=3 ≥ full swing: the budget never binds, so RP=EEV=WS. Either way VSS=0 —
    the trap from formulation §R2.3, reproduced exactly.
    """
    scen = _scen([[10.0, 50.0, 20.0], [20.0, 40.0, 10.0]], [0.5, 0.5])
    res = value_of_stochastic_solution(scen, BatterySpec(), rho=rho)
    assert res.vss == pytest.approx(0.0, abs=TOL)
    assert res.evpi >= -TOL


# --------------------------------------------------- S = 1 reduces to R1.1 solve


def test_single_scenario_reduces_to_deterministic() -> None:
    """With one scenario the whole apparatus equals the deterministic R1.1 solve."""
    path = [10.0, 50.0, 20.0, 15.0]
    scen = _scen([path], [1.0])
    det = solve(path, BatterySpec()).objective
    res = value_of_stochastic_solution(scen, BatterySpec(), rho=0.5)
    assert res.ev == pytest.approx(det, abs=TOL)
    assert res.rp == pytest.approx(det, abs=TOL)
    assert res.ws == pytest.approx(det, abs=TOL)
    assert res.vss == pytest.approx(0.0, abs=TOL)
    assert res.evpi == pytest.approx(0.0, abs=TOL)


# ---------------------------------------------- VSS > 0 escape (measured, gated)


def test_vss_strictly_positive_on_designed_instance() -> None:
    """A shared cheap-charge hour + scenario-specific discharge peak ⇒ VSS > 0.

    Both scenarios are cheap at t0 (a common charge opportunity a single g^DA can
    commit to) but peak at *different* later hours, so a mean-committed discharge
    is a poor centre while a neutral commitment plus per-scenario recourse wins.
    """
    scen = _scen([[5.0, 50.0, 10.0, 10.0], [5.0, 10.0, 50.0, 10.0]], [0.5, 0.5])
    batt = BatterySpec(capacity=2.0, soc_initial=0.5, soc_terminal=0.5)
    res = value_of_stochastic_solution(scen, batt, rho=0.5)
    assert res.eev <= res.rp + TOL
    assert res.rp <= res.ws + TOL
    assert res.vss > 1e-3  # measured, strictly positive — escapes the trap
