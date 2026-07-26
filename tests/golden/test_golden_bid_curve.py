"""Golden oracles for R2.6: price-contingent day-ahead bid curves (formulation-r2 §R2.6).

Every number below is hand-computed on a designed instance, not read off a solver.
The arithmetic is deliberately trivial: a 2 MWh / 1 MW battery at eta = 1 with
e_0 = e_tgt = 1 MWh over T = 2, so the terminal-SoC constraint reduces every
feasible dispatch to ``g = [a, -a]`` with ``a`` in [-1, 1] (net export, grid-side).
A branch's profit is then linear in ``a`` and the optimum sits at an endpoint.

The five oracles, in the order they matter:

1. **Collapse identity.** Pin the first stage and the bid-curve program returns the
   same objective as R2.3, exactly. This is the settlement algebra: §R2.3's own
   expectation already reduces to E_s[sum_t dt pi^(s)_t g^(s)_t], which is what
   R2.6 maximizes directly, so the two agree at lambda = 0.
2. **The escape.** At rho = 0 the scalar commitment must pick one blind schedule
   and earns nothing; the curve sells in the expensive state and buys in the cheap
   one.
3. **Monotonicity binds.** A high price early is worth charging into when a much
   higher price follows, so the ideal contingent quantity can *fall* as the price
   rises. The auction forbids that, and the curve is forced flat.
4. **Ties.** Two scenarios the auction prices identically at an hour must receive
   the same quantity there, whatever the rest of their paths do.
5. **The rho limit.** With a budget wide enough that it never binds, the curve is
   worth nothing over the scalar commitment.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bess.assets.battery import BatterySpec
from bess.scenarios import ScenarioSet
from bess.stochastic import solve_stochastic

TOL = 1e-6

# 2 MWh / 1 MW, lossless, starting and ending half full: every feasible T=2
# dispatch is g = [a, -a], so the hand arithmetic below is exact.
_BATT = BatterySpec(
    capacity=2.0,
    soc_min=0.0,
    soc_initial=0.5,
    soc_terminal=0.5,
    eta_charge=1.0,
    eta_discharge=1.0,
)


def _scen(paths: list[list[float]], probs: list[float]) -> ScenarioSet:
    arr = np.asarray(paths, dtype=float)
    idx = pd.date_range("2026-01-01", periods=arr.shape[1], freq="h", tz="UTC")
    return ScenarioSet(paths=arr, probs=np.asarray(probs, dtype=float), index=idx)


# ------------------------------------------------------ 1. the collapse identity


def test_pinned_first_stage_reproduces_r23_exactly() -> None:
    """Same fixed commitment, same objective, both programs, at lambda = 0.

    g^DA = [-1, +1] (charge then discharge) with rho = 0.5 leaves each branch
    a in [-1, -0.5]. Branch [10, 90] earns -80a, best at a = -1 -> 80; branch
    [90, 10] earns +80a, best at a = -0.5 -> -40. Expectation 0.5(80 - 40) = 20.
    """
    scen = _scen([[10.0, 90.0], [90.0, 10.0]], [0.5, 0.5])
    fix_da = ([1.0, 0.0], [0.0, 1.0])  # (p_charge, p_discharge)

    scalar = solve_stochastic(scen, _BATT, rho=0.5, fix_da=fix_da, bid_curve=False)
    curve = solve_stochastic(scen, _BATT, rho=0.5, fix_da=fix_da, bid_curve=True)

    assert scalar.objective == pytest.approx(20.0, abs=TOL)
    assert curve.objective == pytest.approx(20.0, abs=TOL)
    assert curve.objective == pytest.approx(scalar.objective, abs=TOL)
    # Pinning collapses every branch onto the one commitment.
    for branch in curve.g_da_branches:
        assert branch == pytest.approx([-1.0, 1.0], abs=TOL)


# --------------------------------------------------------------- 2. the escape


def test_curve_beats_a_blind_commitment_at_zero_recourse() -> None:
    """rho = 0: the scalar earns 0, the curve earns the full 80.

    Mean prices are [50, 50], so *any* feasible single commitment g = [a, -a]
    settles at 50a - 50a = 0. The curve charges at 10 and discharges at 90 in
    each state instead: branch [10, 90] takes a = -1 (80), branch [90, 10] takes
    a = +1 (80). Monotonicity is satisfied, not slack luck: at hour 0 the cheap
    state buys and the expensive state sells, which is the right order.
    """
    scen = _scen([[10.0, 90.0], [90.0, 10.0]], [0.5, 0.5])

    scalar = solve_stochastic(scen, _BATT, rho=0.0, bid_curve=False)
    curve = solve_stochastic(scen, _BATT, rho=0.0, bid_curve=True)

    assert scalar.objective == pytest.approx(0.0, abs=TOL)
    assert curve.objective == pytest.approx(80.0, abs=TOL)
    assert curve.g_da_branches[0] == pytest.approx([-1.0, 1.0], abs=TOL)
    assert curve.g_da_branches[1] == pytest.approx([1.0, -1.0], abs=TOL)
    # Hour 0 curve: buy 1 MW at 10, sell 1 MW at 90. Nondecreasing in price.
    # Prices are tick-exact; quantities come off the solver, so they get a tolerance.
    assert [p for p, _ in curve.curve[0]] == [10.0, 90.0]
    assert [q for _, q in curve.curve[0]] == pytest.approx([-1.0, 1.0], abs=TOL)


# ------------------------------------------------------- 3. monotonicity binds


def test_monotonicity_binds_and_costs_the_curve_its_contingency() -> None:
    """The ideal quantity falls as the price rises, so the auction forces it flat.

    Branch [60, 10] wants to sell at 60 and buy back at 10 (a = +1, profit 50).
    Branch [80, 500] wants to buy at 80 to sell at 500 (a = -1, profit 420). At
    hour 0 the *higher* price (80) wants the *lower* quantity, which no monotone
    curve can express, and hour 1 orders the pair the other way, so both hours
    force equality: a_1 = a_2 = a. The objective becomes -185a, best at a = -1.

    Unconstrained contingency would be 0.5(50) + 0.5(420) = 235. A program that
    returns 235 is not enforcing the auction rule, which is what this pins.
    """
    scen = _scen([[60.0, 10.0], [80.0, 500.0]], [0.5, 0.5])

    curve = solve_stochastic(scen, _BATT, rho=0.0, bid_curve=True)
    scalar = solve_stochastic(scen, _BATT, rho=0.0, bid_curve=False)

    assert curve.objective == pytest.approx(185.0, abs=TOL)
    assert curve.objective < 235.0 - 1e-3  # the clairvoyant value is unreachable
    # Fully bound: here the curve buys no contingency at all over the scalar.
    assert curve.objective == pytest.approx(scalar.objective, abs=TOL)
    assert curve.g_da_branches[0] == pytest.approx(curve.g_da_branches[1], abs=TOL)


# ------------------------------------------------------------------- 4. ties


@pytest.mark.parametrize(
    "paths",
    [
        [[50.0, 10.0], [50.0, 500.0]],
        [[50.0, 500.0], [50.0, 10.0]],  # mirrored, so a one-sided rule cannot pass both
    ],
)
def test_equal_prices_force_equal_quantities(paths: list[list[float]]) -> None:
    """Hour 0 clears at 50 in both states, so the auction cannot tell them apart.

    Left to itself the program would sell at 50 in the [50, 10] state (a = +1,
    profit 40) and buy at 50 in the [50, 500] state (a = -1, profit 450), worth
    245 in expectation. That reads the rest of the path through a price the
    auction prices identically, which is anticipativity, not a bid curve. The tie
    family forces a_1 = a_2 = a, the objective becomes -205a, best at a = -1.
    """
    scen = _scen(paths, [0.5, 0.5])

    curve = solve_stochastic(scen, _BATT, rho=0.0, bid_curve=True)

    assert curve.objective == pytest.approx(205.0, abs=TOL)
    assert curve.objective < 245.0 - 1e-3
    assert curve.g_da_branches[0][0] == pytest.approx(curve.g_da_branches[1][0], abs=TOL)
    # One tied price, so hour 0's curve is a single step.
    assert [p for p, _ in curve.curve[0]] == [50.0]
    assert [q for _, q in curve.curve[0]] == pytest.approx([-1.0], abs=TOL)


# ---------------------------------------------------------------- 5. rho limit


def test_curve_is_worthless_when_the_budget_never_binds() -> None:
    """rho large: both programs reach the wait-and-see value, so the curve adds 0.

    Each branch earns 80 under perfect foresight, so both objectives are 80. This
    is the R2.6 restatement of §R2.3's rho-limit collapse: the commitment only
    ever mattered through the budget.
    """
    scen = _scen([[10.0, 90.0], [90.0, 10.0]], [0.5, 0.5])

    scalar = solve_stochastic(scen, _BATT, rho=3.0, bid_curve=False)
    curve = solve_stochastic(scen, _BATT, rho=3.0, bid_curve=True)

    assert scalar.objective == pytest.approx(80.0, abs=TOL)
    assert curve.objective == pytest.approx(80.0, abs=TOL)
    assert curve.objective - scalar.objective == pytest.approx(0.0, abs=TOL)
