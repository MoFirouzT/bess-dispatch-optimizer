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


@dataclass
class Schedule:
    """Solved dispatch. All lists are length T (one entry per period)."""

    p_charge: list[float]  # grid-side MW per period
    p_discharge: list[float]  # grid-side MW per period
    soc: list[float]  # MWh, end of each period
    objective: float  # EUR (solver-reported)


def build_model(
    prices: Sequence[float], battery: BatterySpec, dt: float = 1.0
) -> pyo.ConcreteModel:
    """Assemble the Pyomo MILP: asset registers physics, optimizer adds the objective."""
    model = pyo.ConcreteModel(name="bess_r11")
    Battery(battery).register(model, prices, dt)

    # Objective — grid-side arbitrage revenue. NO efficiency factor here.
    model.revenue = pyo.Objective(
        expr=sum(prices[t] * dt * (model.p_discharge[t] - model.p_charge[t]) for t in model.T),
        sense=pyo.maximize,
    )
    return model


def solve(
    prices: Sequence[float],
    battery: BatterySpec,
    dt: float = 1.0,
    solver: str = "appsi_highs",
) -> Schedule:
    """Solve the deterministic dispatch and return the optimal schedule."""
    model = build_model(prices, battery, dt)
    results = pyo.SolverFactory(solver).solve(model)

    # Fail loud if not optimal (structured infeasibility handling is R1.3).
    tc = results.solver.termination_condition
    if tc != TerminationCondition.optimal:
        raise RuntimeError(f"solve did not reach optimality: termination_condition={tc}")

    idx = sorted(model.T)
    return Schedule(
        p_charge=[pyo.value(model.p_charge[t]) for t in idx],
        p_discharge=[pyo.value(model.p_discharge[t]) for t in idx],
        soc=[pyo.value(model.soc[t]) for t in idx],
        objective=pyo.value(model.revenue),
    )
