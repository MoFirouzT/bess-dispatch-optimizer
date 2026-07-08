"""Deterministic MILP core — builds and solves the R1.1 dispatch model.

Formulation: ``docs/formulation.md`` § "R1.1 — Deterministic core". The objective
is grid-side arbitrage cash flow with **no efficiency term**; efficiency lives in
the SoC balance, registered by the ``Battery`` asset. This module imports
``assets`` only and must never import ``api`` (import-linter contract).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pyomo.environ as pyo
from pyomo.opt import TerminationCondition

from bess.assets.battery import Battery, BatterySpec
from bess.validation.preflight import check

# Tight HiGHS tolerances so each solve reaches the true optimum to ~1e-9, keeping
# cross-solve objective comparisons (R1.2 "degradation never pays") sound at 1e-6.
_HIGHS_TOLERANCES = {
    "mip_rel_gap": 1e-9,
    "mip_abs_gap": 1e-9,
    "primal_feasibility_tolerance": 1e-9,
    "dual_feasibility_tolerance": 1e-9,
}


@dataclass
class Schedule:
    """Solved dispatch. All lists are length T (one entry per period)."""

    p_charge: list[float]  # grid-side MW per period
    p_discharge: list[float]  # grid-side MW per period
    soc: list[float]  # MWh, end of each period
    objective: float  # EUR (objective expression at the solution)
    termination: str = "optimal"  # solver termination condition for this schedule


def build_model(
    prices: Sequence[float], battery: BatterySpec, dt: float = 1.0
) -> pyo.ConcreteModel:
    """Assemble the Pyomo MILP: asset registers physics, optimizer adds the objective."""
    model = pyo.ConcreteModel(name="bess_dispatch")
    Battery(battery).register(model, prices, dt)

    # Objective — grid-side arbitrage revenue (NO efficiency factor) minus the
    # asset-provided degradation cost (R1.2; zero/absent ⇒ identical to R1.1).
    revenue = sum(prices[t] * dt * (model.p_discharge[t] - model.p_charge[t]) for t in model.T) # type: ignore[operator]
    degradation = (
        sum(model.degradation_cost[t] for t in model.T) if hasattr(model, "degradation_cost") else 0 # type: ignore[operator]
    )
    model.revenue = pyo.Objective(expr=revenue - degradation, sense=pyo.maximize)
    return model


def solve(
    prices: Sequence[float],
    battery: BatterySpec,
    dt: float = 1.0,
    solver: str = "appsi_highs",
    *,
    time_limit: float | None = None,
) -> Schedule:
    """Solve the deterministic dispatch and return the optimal schedule.

    Runs pre-flight validation first (R1.3): predictable bad input / provable
    infeasibility surfaces as a structured ``PreflightError`` before the solver is
    touched. The optimality guard below remains for the residual class (e.g.
    ramp-coupled infeasibility) that pre-flight cannot prove.

    ``time_limit`` (seconds) bounds the solver's run; if it expires without a proven
    optimum the termination is non-optimal and this raises ``RuntimeError`` (the
    R1.5 circuit breaker catches that and serves the greedy fallback).
    """
    check(prices, battery, dt)
    model = build_model(prices, battery, dt)
    # load_solutions=False so a residual (e.g. ramp-coupled) infeasibility returns
    # a termination condition to guard on, rather than raising on solution load.
    opt = pyo.SolverFactory(solver)
    # Solve to a tight optimum. HiGHS's defaults (~1e-6/1e-7 gap & feasibility) can
    # leave each solve a few ×1e-6 short of the true optimum; when two near-identical
    # solves are compared (e.g. with- vs without-degradation), those independent gaps
    # need not cancel and can break invariants like "degradation never pays" at the
    # 1e-6 scale. Tightening makes each solve accurate enough that the comparison is
    # sound. This *strengthens* accuracy; it does not loosen any test tolerance.
    for _key, _val in _HIGHS_TOLERANCES.items():
        opt.options[_key] = _val
    if time_limit is not None:
        opt.config.time_limit = time_limit # type: ignore[attr-defined]
    results = opt.solve(model, load_solutions=False)

    # Fail loud if not optimal — pre-flight (check, above) handles the predictable
    # class; this guards the residual class it cannot prove.
    tc = results.solver.termination_condition
    if tc != TerminationCondition.optimal:
        raise RuntimeError(f"solve did not reach optimality: termination_condition={tc}")
    model.solutions.load_from(results)

    # Enforce D_t >= 0 (R1.2): the degradation cost is a convex PWL through the
    # origin, so it is non-negative at every solution. HiGHS presolve can return a
    # sub-tolerance *negative* D_t for near-zero cost curves (the top segment's line
    # back-extrapolated below 0 at tau=0); left unclamped, that slack inflates the
    # objective above the no-degradation value. Clamp the numerical noise here; a
    # materially negative D_t means the convex-PWL invariant is genuinely broken, so
    # surface it rather than hide it.
    if hasattr(model, "degradation_cost"):
        for t in model.T: # type: ignore[index]
            d = pyo.value(model.degradation_cost[t]) # type: ignore[index]
            if d < 0.0: # type: ignore[operator]
                if d < -1e-5: # type: ignore[operator]
                    raise RuntimeError(
                        f"degradation_cost[{t}]={d!r} is materially negative — "
                        "convex-PWL non-negativity (formulation §R1.2) violated"
                    )
                model.degradation_cost[t].set_value(0.0) # type: ignore[index]

    idx = sorted(model.T) # type: ignore[index]
    return Schedule(
        p_charge=[pyo.value(model.p_charge[t]) for t in idx], # type: ignore[index]
        p_discharge=[pyo.value(model.p_discharge[t]) for t in idx], # type: ignore[index]
        soc=[pyo.value(model.soc[t]) for t in idx], # type: ignore[index]
        objective=pyo.value(model.revenue), # type: ignore[index]
        termination="optimal",  # guard above guarantees optimality at this point
    )
