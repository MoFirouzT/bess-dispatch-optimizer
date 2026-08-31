"""Risk-aware two-stage dispatch over a scenario set (R2.3).

Formulation: ``docs/formulation-uncertainty.md`` § R2.3. A non-anticipative day-ahead net
schedule ``g^DA`` (first stage) plus per-scenario recourse dispatch ``g^(s)``
(second stage, full R1.1 physics at the realised price ``π^(s)``), coupled by a
recourse budget ``|g^(s) − g^DA| ≤ ρ·P̄``. The objective is the CVaR mean-risk
combination ``(1−λ)·E[profit] − λ·CVaR_α(loss)`` (Rockafellar-Uryasev). Settling
the day-ahead volume at the scenario-mean price ``π̄`` and the intraday deviation
at ``π^(s)`` makes ``g^DA`` enter only through the budget, so a finite ρ gives a
strictly positive value of the stochastic solution (§R2.3,
docs/decisions/risk-aware-two-stage-design.md/0020).

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


# Day-ahead prices are quoted to the cent, so equality at this resolution is what
# "the auction cannot tell these two states apart" means (§R2.6, spec decision 3).
_PRICE_TICK_EUR_MWH = 0.01


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
    # R2.6 only (None on the R2.3 path): the price-contingent commitment.
    g_da_branches: list[list[float]] | None = None  # (S, T) one commitment per scenario
    curve: list[list[tuple[float, float]]] | None = None  # per hour, the (price, quantity) steps


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
    bid_curve: bool = False,
    commitment: np.ndarray | None = None,
) -> tuple[pyo.ConcreteModel, dict]:
    s_n, t_n = paths.shape
    # Day-ahead settlement price: the scenario mean by default; an explicit π^DA is
    # passed when evaluating a fixed commitment on *held-out* paths (out-of-sample
    # VSS), so the DA leg settles at the training price, not the held-out one.
    # Unused under a bid curve, where both legs settle at the realised π^(s) (§R2.6).
    pi_da = probs @ paths if pi_da is None else np.asarray(pi_da, dtype=float)
    p_rated = max(battery.p_charge_max, battery.p_discharge_max)
    budget = rho * p_rated

    if bid_curve:
        name = "r26_bid_curve"
    elif commitment is not None:
        name = "r26_obligation_scoring"
    else:
        name = "r23_two_stage"
    m = pyo.ConcreteModel(name=name)
    m.S = pyo.RangeSet(0, s_n - 1)

    # First-stage day-ahead block(s), each with its own R1.1 physics (prices set the
    # length only). R2.3 commits one schedule shared by every scenario; R2.6 carries
    # one branch per scenario, each deliverable in its own right. Under obligation
    # scoring (§R2.6 evaluation) there is no day-ahead block at all: the commitment
    # is a *quantity obligation*, not a schedule, so it enters only the budget below.
    if commitment is not None:
        pass
    elif bid_curve:
        m.da = pyo.Block(m.S, rule=lambda b, s: Battery(battery).register(b, paths[s].tolist(), dt))
    else:
        m.da = pyo.Block(rule=lambda b: Battery(battery).register(b, pi_da.tolist(), dt))
    # Per-scenario recourse blocks (full R1.1 physics at each realised path).
    m.scen = pyo.Block(m.S, rule=lambda b, s: Battery(battery).register(b, paths[s].tolist(), dt))

    if fix_da is not None:  # EEV: pin the first stage to a given schedule (every branch)
        pch, pdis = fix_da
        blocks = [m.da[s] for s in range(s_n)] if bid_curve else [m.da]
        for block in blocks:
            for t in range(t_n):
                block.p_charge[t].fix(float(pch[t]))
                block.p_discharge[t].fix(float(pdis[t]))

    def g_da(s, t):  # net export (grid-side) of scenario s's commitment branch
        if commitment is not None:
            return float(commitment[t])
        block = m.da[s] if bid_curve else m.da
        return block.p_discharge[t] - block.p_charge[t]

    def g_sc(s, t):  # net export of scenario s
        return m.scen[s].p_discharge[t] - m.scen[s].p_charge[t]

    # Recourse budget: |g^(s)_t − g^DA,(s)_t| ≤ ρ·P̄ (one commitment on the R2.3 path).
    m.Tset = pyo.RangeSet(0, t_n - 1)
    m.budget_hi = pyo.Constraint(
        m.S, m.Tset, rule=lambda mm, s, t: g_sc(s, t) - g_da(s, t) <= budget
    )
    m.budget_lo = pyo.Constraint(
        m.S, m.Tset, rule=lambda mm, s, t: g_sc(s, t) - g_da(s, t) >= -budget
    )

    if bid_curve or commitment is not None:
        if bid_curve:
            _register_curve_constraints(m, paths, g_da)
        # profit_s = Σ_t Δt [π^(s)_t g^DA,(s)_t + π^(s)_t (g^(s)_t − g^DA,(s)_t)], which
        # cancels to the realised cash flow: both legs settle at the clearing price.
        profit = {s: sum(dt * paths[s][t] * g_sc(s, t) for t in range(t_n)) for s in range(s_n)}
    else:
        # profit_s = Σ_t Δt [ π^DA_t·g^DA_t + π^(s)_t·(g^(s)_t − g^DA_t) ].
        profit = {
            s: sum(
                dt * (pi_da[t] * g_da(s, t) + paths[s][t] * (g_sc(s, t) - g_da(s, t)))
                for t in range(t_n)
            )
            for s in range(s_n)
        }
    exp_profit = sum(probs[s] * profit[s] for s in range(s_n))

    # CVaR mean-risk objective (Rockafellar-Uryasev): loss L_s = −profit_s.
    m.zeta = pyo.Var(domain=pyo.Reals)  # VaR auxiliary (house eta is efficiency)
    m.z = pyo.Var(m.S, domain=pyo.NonNegativeReals)  # tail slacks
    m.cvar_cut = pyo.Constraint(m.S, rule=lambda mm, s: mm.z[s] >= -profit[s] - mm.zeta)
    cvar = m.zeta + (1.0 / (1.0 - alpha)) * sum(probs[s] * m.z[s] for s in range(s_n))
    m.obj = pyo.Objective(expr=(1.0 - lambda_) * exp_profit - lambda_ * cvar, sense=pyo.maximize)

    ctx = {
        "profit": profit,
        "probs": probs,
        "S": s_n,
        "T": t_n,
        "alpha": alpha,
        "bid_curve": bid_curve,
    }
    return m, ctx


def _tick_keys(prices: np.ndarray) -> np.ndarray:
    """Prices as integer multiples of the market tick: the resolution ties are judged at."""
    return np.rint(prices / _PRICE_TICK_EUR_MWH).astype(np.int64)


def _register_curve_constraints(m: pyo.ConcreteModel, paths: np.ndarray, g_da) -> None:
    """The two families that make the branches a submittable bid curve (§R2.6).

    Within each hour, sort the scenarios by that hour's clearing price and constrain
    adjacent pairs: strictly rising price gives ``≤`` (monotone, also an exchange
    rule), equal price gives ``==`` (ties). Chaining adjacent pairs imposes the full
    order in ``S-1`` constraints per hour rather than ``S²``. Together they make the
    commitment a nondecreasing function of that hour's price *alone*, which is the
    measurability condition: without the tie family the program could read the rest
    of the path through prices the auction prices identically.
    """
    keys = _tick_keys(paths)  # (S, T)
    t_n = paths.shape[1]
    m.curve_monotone = pyo.ConstraintList()
    m.curve_tie = pyo.ConstraintList()
    for t in range(t_n):
        order = np.argsort(keys[:, t], kind="stable")
        for lo, hi in zip(order, order[1:], strict=False):
            if keys[lo, t] == keys[hi, t]:
                m.curve_tie.add(g_da(int(lo), t) == g_da(int(hi), t))
            else:
                m.curve_monotone.add(g_da(int(lo), t) <= g_da(int(hi), t))


def curve_response(
    curve: list[list[tuple[float, float]]], prices: Sequence[float] | np.ndarray
) -> list[float]:
    """The commitment a submitted curve incurs at a realised price path (§R2.6).

    Per hour, the auction accepts the quantity of the last step whose price the
    realisation reaches: ``q_t(π) = q_{t,j}`` for the largest ``j`` with
    ``p_{t,j} ≤ π``, with the lowest step extended downward. Reading the curve at
    the prices it was built from returns exactly the branch committed in that
    state, which is the measurability condition restated as a round trip.

    The result is a *quantity obligation*, not a schedule: assembled across hours
    from different branches it generally violates the SoC balance, which is why
    the evaluation program scores it through the budget alone.
    """
    if len(curve) != len(prices):
        raise ValueError(f"curve covers {len(curve)} periods; got {len(prices)} prices")
    out = []
    for steps, price in zip(curve, prices, strict=True):
        quantity = steps[0][1]
        for step_price, step_quantity in steps:
            if step_price <= price:
                quantity = step_quantity
        out.append(float(quantity))
    return out


def _extract_curve(
    branches: list[list[float]], paths: np.ndarray
) -> list[list[tuple[float, float]]]:
    """Collapse the solved branches to per-hour ``(price, quantity)`` steps.

    One step per distinct tick-rounded price, sorted ascending. Tied branches are
    equal by construction, so averaging them only removes solver noise.

    A step takes the **lowest raw price** in its tie group, not the rounded value:
    rounding to nearest can land above a member's own price, and then reading the
    curve back at that price (``p ≤ π``) would fall through to the step below and
    return a quantity the program never committed in that state. Tie groups are at
    least a tick apart, so the lowest raw price keeps them strictly ordered.
    """
    keys = _tick_keys(paths)
    _, t_n = paths.shape
    curve: list[list[tuple[float, float]]] = []
    for t in range(t_n):
        steps: dict[int, tuple[float, list[float]]] = {}
        for s, branch in enumerate(branches):
            key = int(keys[s, t])
            price, quantities = steps.get(key, (float(paths[s, t]), []))
            steps[key] = (min(price, float(paths[s, t])), [*quantities, branch[t]])
        curve.append([(price, float(np.mean(qs))) for _, (price, qs) in sorted(steps.items())])
    return curve


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
    bid_curve: bool = False,
    commitment: Sequence[float] | np.ndarray | None = None,
) -> StochasticSchedule:
    """Solve the risk-aware two-stage program over ``scenarios``.

    ``lambda_=0`` is the risk-neutral recourse problem (RP); ``lambda_>0`` adds the
    CVaR term (``alpha`` is the tail level). ``rho`` is the recourse fraction (the
    budget is ``ρ·P̄``). ``fix_da`` pins the first stage to a given
    ``(p_charge, p_discharge)`` schedule, used to evaluate the EEV. ``pi_da`` sets
    the day-ahead settlement price (default the scenario mean); pass the *training*
    price when evaluating a fixed commitment on held-out paths (out-of-sample VSS).

    ``bid_curve=True`` switches on the R2.6 delta: the commitment is indexed by
    scenario and constrained to be monotone in, and single-valued in, each hour's
    clearing price, so what is committed is a submittable curve rather than one
    schedule. Both legs then settle at the realised clearing price, which makes
    ``pi_da`` meaningless, and the returned ``g_da`` is only a probability-weighted
    summary of the branches: ``g_da_branches`` and ``curve`` are the decision.
    ``bid_curve=False`` (the default) is the R2.3 program, unchanged.

    ``commitment`` scores an already-decided commitment as a **quantity obligation**
    rather than a schedule (§R2.6 evaluation semantics): the net-export vector enters
    only the recourse budget, no day-ahead block is built, and the recourse dispatch
    carries the R1.1 physics. This is what a curve's *realised* commitment needs,
    since it is assembled across branches and is generally not a schedule; where the
    commitment happens to be R1.1-feasible it agrees exactly with the ``fix_da``
    path. Mutually exclusive with ``fix_da``, ``pi_da`` and ``bid_curve``.
    """
    if bid_curve and pi_da is not None:
        raise ValueError(
            "pi_da does not apply under bid_curve=True: a bid curve settles both legs "
            "at the realised clearing price, so there is no separate day-ahead price"
        )
    if commitment is not None and (fix_da is not None or pi_da is not None or bid_curve):
        raise ValueError(
            "commitment scores a decided obligation and cannot be combined with "
            "fix_da, pi_da or bid_curve"
        )
    paths = np.asarray(scenarios.paths, dtype=float)
    probs = np.asarray(scenarios.probs, dtype=float)
    da_price = None if pi_da is None else np.asarray(pi_da, dtype=float)
    obligation = None if commitment is None else np.asarray(commitment, dtype=float)
    m, ctx = _build(
        paths, probs, battery, dt, alpha, lambda_, rho, fix_da, da_price, bid_curve, obligation
    )

    opt = pyo.SolverFactory(solver)
    for key, val in _HIGHS_TOLERANCES.items():
        opt.options[key] = val
    results = opt.solve(m, load_solutions=False)
    tc = results.solver.termination_condition
    if tc != TerminationCondition.optimal:
        raise RuntimeError(f"stochastic solve did not reach optimality: termination_condition={tc}")
    m.solutions.load_from(results)

    s_n, t_n = ctx["S"], ctx["T"]
    branches: list[list[float]] | None = None
    curve: list[list[tuple[float, float]]] | None = None
    if bid_curve:
        branches = [
            [pyo.value(m.da[s].p_discharge[t]) - pyo.value(m.da[s].p_charge[t]) for t in range(t_n)]
            for s in range(s_n)
        ]
        curve = _extract_curve(branches, paths)
        # No single commitment exists under a curve; report the weighted mean branch.
        g_da = (probs @ np.asarray(branches, dtype=float)).tolist()
    elif obligation is not None:
        g_da = obligation.tolist()  # the scored obligation, echoed back
    else:
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
        g_da_branches=branches,
        curve=curve,
    )
