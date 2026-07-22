"""Risk-aware two-stage dispatch over a scenario set (R2.3).

Formulation: ``docs/formulation.md`` § R2.3. A non-anticipative day-ahead net
schedule ``g^DA`` (first stage) plus per-scenario recourse dispatch ``g^(s)``
(second stage, full R1.1 physics at the realised price ``π^(s)``), coupled by a
recourse budget ``|g^(s) − g^DA| ≤ ρ·P̄``. The objective is the CVaR mean-risk
combination ``(1−λ)·E[profit] − λ·CVaR_α(loss)`` (Rockafellar-Uryasev). Settling
the day-ahead volume at the scenario-mean price ``π̄`` and the intraday deviation
at ``π^(s)`` makes ``g^DA`` enter only through the budget, so a finite ρ gives a
strictly positive value of the stochastic solution (§R2.3, ADR-0019/0020).

This module imports ``optimizer`` / ``assets`` only (import-linter core chain).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pyomo.environ as pyo
from pyomo.opt import TerminationCondition

from bess.assets.battery import Battery, BatterySpec
from bess.optimizer.core import _HIGHS_TOLERANCES
from bess.stochastic.risk import cvar_from_losses

if TYPE_CHECKING:  # annotation only; no runtime dependency on the scenarios layer
    from bess.scenarios import ScenarioSet


@dataclass
class StochasticSchedule:
    """Solved two-stage dispatch (grid-side net export, MW per period)."""

    g_da: list[float]  # first-stage day-ahead commitment, length T
    recourse: list[list[float]]  # per-scenario recourse net export, shape (S, T)
    expected_profit: float  # Σ_s p_s profit_s (EUR)
    cvar: float  # CVaR_α of the loss (EUR)
    var: float  # VaR_α (the CVaR minimiser η, EUR)
    objective: float  # the mean-risk objective value at the solution
    termination: str = "optimal"


def _build(
    paths: np.ndarray,
    probs: np.ndarray,
    battery: BatterySpec,
    dt: float,
    alpha: float,
    lambda_: float,
    rho: float,
    fix_da: tuple[Sequence[float], Sequence[float]] | None,
    pi_da: np.ndarray | None,
) -> tuple[pyo.ConcreteModel, dict]:
    s_n, t_n = paths.shape
    # Day-ahead settlement price: the scenario mean by default; an explicit π^DA is
    # passed when evaluating a fixed commitment on *held-out* paths (out-of-sample
    # VSS), so the DA leg settles at the training price, not the held-out one.
    pi_da = probs @ paths if pi_da is None else np.asarray(pi_da, dtype=float)
    p_rated = max(battery.p_charge_max, battery.p_discharge_max)
    budget = rho * p_rated

    m = pyo.ConcreteModel(name="r23_two_stage")

    # First-stage day-ahead block (its own R1.1 physics; prices set the length only).
    m.da = pyo.Block(rule=lambda b: Battery(battery).register(b, pi_da.tolist(), dt))
    # Per-scenario recourse blocks (full R1.1 physics at each realised path).
    m.S = pyo.RangeSet(0, s_n - 1)
    m.scen = pyo.Block(m.S, rule=lambda b, s: Battery(battery).register(b, paths[s].tolist(), dt))

    if fix_da is not None:  # EEV: pin the first stage to a given schedule
        pch, pdis = fix_da
        for t in range(t_n):
            m.da.p_charge[t].fix(float(pch[t]))
            m.da.p_discharge[t].fix(float(pdis[t]))

    def g_da(t):  # net export (grid-side) of the commitment
        return m.da.p_discharge[t] - m.da.p_charge[t]

    def g_sc(s, t):  # net export of scenario s
        return m.scen[s].p_discharge[t] - m.scen[s].p_charge[t]

    # Recourse budget: |g^(s)_t − g^DA_t| ≤ ρ·P̄.
    m.Tset = pyo.RangeSet(0, t_n - 1)
    m.budget_hi = pyo.Constraint(m.S, m.Tset, rule=lambda mm, s, t: g_sc(s, t) - g_da(t) <= budget)
    m.budget_lo = pyo.Constraint(m.S, m.Tset, rule=lambda mm, s, t: g_sc(s, t) - g_da(t) >= -budget)

    # profit_s = Σ_t Δt [ π^DA_t·g^DA_t + π^(s)_t·(g^(s)_t − g^DA_t) ].
    profit = {
        s: sum(dt * (pi_da[t] * g_da(t) + paths[s][t] * (g_sc(s, t) - g_da(t))) for t in range(t_n))
        for s in range(s_n)
    }
    exp_profit = sum(probs[s] * profit[s] for s in range(s_n))

    # CVaR mean-risk objective (Rockafellar-Uryasev): loss L_s = −profit_s.
    m.eta = pyo.Var(domain=pyo.Reals)  # VaR auxiliary
    m.z = pyo.Var(m.S, domain=pyo.NonNegativeReals)  # tail slacks
    m.cvar_cut = pyo.Constraint(m.S, rule=lambda mm, s: mm.z[s] >= -profit[s] - mm.eta)
    cvar = m.eta + (1.0 / (1.0 - alpha)) * sum(probs[s] * m.z[s] for s in range(s_n))
    m.obj = pyo.Objective(expr=(1.0 - lambda_) * exp_profit - lambda_ * cvar, sense=pyo.maximize)

    ctx = {"profit": profit, "probs": probs, "S": s_n, "T": t_n, "alpha": alpha}
    return m, ctx


def solve_stochastic(
    scenarios: ScenarioSet,
    battery: BatterySpec,
    *,
    dt: float = 1.0,
    alpha: float = 0.95,
    lambda_: float = 0.0,
    rho: float = 0.5,
    solver: str = "appsi_highs",
    fix_da: tuple[Sequence[float], Sequence[float]] | None = None,
    pi_da: Sequence[float] | np.ndarray | None = None,
) -> StochasticSchedule:
    """Solve the risk-aware two-stage program over ``scenarios``.

    ``lambda_=0`` is the risk-neutral recourse problem (RP); ``lambda_>0`` adds the
    CVaR term (``alpha`` is the tail level). ``rho`` is the recourse fraction (the
    budget is ``ρ·P̄``). ``fix_da`` pins the first stage to a given
    ``(p_charge, p_discharge)`` schedule, used to evaluate the EEV. ``pi_da`` sets
    the day-ahead settlement price (default the scenario mean); pass the *training*
    price when evaluating a fixed commitment on held-out paths (out-of-sample VSS).
    """
    paths = np.asarray(scenarios.paths, dtype=float)
    probs = np.asarray(scenarios.probs, dtype=float)
    da_price = None if pi_da is None else np.asarray(pi_da, dtype=float)
    m, ctx = _build(paths, probs, battery, dt, alpha, lambda_, rho, fix_da, da_price)

    opt = pyo.SolverFactory(solver)
    for key, val in _HIGHS_TOLERANCES.items():
        opt.options[key] = val
    results = opt.solve(m, load_solutions=False)
    tc = results.solver.termination_condition
    if tc != TerminationCondition.optimal:
        raise RuntimeError(f"stochastic solve did not reach optimality: termination_condition={tc}")
    m.solutions.load_from(results)

    s_n, t_n = ctx["S"], ctx["T"]
    g_da = [pyo.value(m.da.p_discharge[t]) - pyo.value(m.da.p_charge[t]) for t in range(t_n)]
    recourse = [
        [pyo.value(m.scen[s].p_discharge[t]) - pyo.value(m.scen[s].p_charge[t]) for t in range(t_n)]
        for s in range(s_n)
    ]
    profits = np.array([pyo.value(ctx["profit"][s]) for s in range(s_n)])
    cvar, var = cvar_from_losses(-profits, probs, ctx["alpha"])
    return StochasticSchedule(
        g_da=g_da,
        recourse=recourse,
        expected_profit=float(np.dot(probs, profits)),
        cvar=cvar,
        var=var,
        objective=float(pyo.value(m.obj)),
    )
