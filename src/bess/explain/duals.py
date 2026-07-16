"""Shadow-price explainability — the SoC-balance dual as a water value (R2.4).

Formulation: ``docs/formulation.md`` § "R2.4. Shadow-price explainability".
Decision: ``docs/decisions/0023-milp-dual-resolve-rule.md``.

A MILP has no LP dual, so the water value is read off by **fix-and-resolve**: solve
the dispatch, fix the mutual-exclusion commitment, and re-solve the resulting LP. The
one subtlety is the idle tie-break (ADR-0023): at an idle period both ``u_t = 0`` and
``u_t = 1`` are optimal and the solver's choice moves the reported dual. The shipped
rule relaxes both exclusion caps at idle periods with ``pi_t >= 0`` (which recovers
the true ``dV/de_0``), keeps the commitment fixed at negative-priced idle periods
(where relaxing would let the LP beat the MILP), and asserts objective equality on
every solve. A no-trade band is reported only where the water value is tie-break
invariant, a property of the flat run.

This module imports ``optimizer``/``assets``/``validation`` only (all below it in the
layering chain) and must never import ``api`` (import-linter contract).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pyomo.environ as pyo
from pyomo.opt import TerminationCondition

from bess.assets.battery import BatterySpec
from bess.optimizer.core import _HIGHS_TOLERANCES, Schedule, build_model, solve

# Power below this (grid-side MW) counts as no trade: distinguishes a real fractional
# dispatch (>= ~1e-2 in practice) from solver noise (~1e-9).
_TOL = 1e-6
# Two water values agree (tie-break invariant) within this.
_PIN_TOL = 1e-5


class DualityError(RuntimeError):
    """The re-solved LP objective did not equal the MILP's.

    The relaxation admitted an action the dispatch model forbids (a SoC-neutral
    round trip the market pays for at a negative price), so the duals are not ones
    the model supports and are not reported. See ADR-0023.
    """


@dataclass(frozen=True)
class FlatRun:
    """Contiguous periods sharing one water value.

    ``mu`` is constant while SoC is interior, so the idle tie-break moves a whole
    run's level, never a single period; ``pinned`` is therefore a property of the run
    (measured constant within every run). A run with no negative-priced idle period is
    pinned; one that has such a period is pinned iff both tie-breaks agree on ``mu``.
    """

    periods: tuple[int, ...]
    water_value_eur_mwh: float
    pinned: bool


@dataclass(frozen=True)
class PeriodExplanation:
    """Per-period explanation of the dispatch decision."""

    action: str  # "charge" | "discharge" | "idle"
    price_eur_mwh: float
    water_value_eur_mwh: float  # mu_t, the SoC-balance dual
    degradation_cost_eur: float  # D_t = c_deg * tau_t
    run: int  # index into Explanation.runs
    reason: str
    # Band edges eta_ch*(mu_t - c_deg) and (mu_t + c_deg)/eta_dis, reported iff the
    # period's run is pinned; None on an unpinned run (the band would contradict the
    # action). At a pinned period the band holds; see ADR-0023.
    band_low_eur_mwh: float | None
    band_high_eur_mwh: float | None
    # Slippage (EUR/MWh grid-side) an executed trade absorbs before it flips; None at
    # idle. A read-off from the band, not a re-optimisation.
    breakeven_slippage_eur_mwh: float | None


@dataclass(frozen=True)
class Explanation:
    """The dispatch schedule plus its per-period and per-run explanation."""

    schedule: Schedule
    runs: list[FlatRun]
    periods: list[PeriodExplanation]


def _action(schedule: Schedule, t: int) -> str:
    if schedule.p_charge[t] > _TOL:
        return "charge"
    if schedule.p_discharge[t] > _TOL:
        return "discharge"
    return "idle"


def _resolve(
    prices: Sequence[float],
    battery: BatterySpec,
    dt: float,
    schedule: Schedule,
    fallback_u: int,
    solver: str,
    milp_objective: float,
) -> list[float]:
    """Fix the commitment (idle rule per ADR-0023), re-solve the LP, return the duals.

    ``fallback_u`` is the commitment forced at negative-priced idle periods (0 or 1);
    both are sound, and comparing the two detects tie-break invariance. Raises
    ``DualityError`` if the re-solved objective does not match the MILP's.
    """
    model = build_model(prices, battery, dt)
    model.u.domain = pyo.Reals  # relax integrality; every u is pinned below
    for t in model.T:  # RangeSet 0..n-1, aligned with the schedule lists
        act = _action(schedule, t)
        if act == "idle" and prices[t] >= 0.0:
            # Relax both exclusion caps to the natural power caps: imposes both band
            # edges at once and recovers the true marginal value.
            model.charge_limit[t].deactivate()
            model.discharge_limit[t].deactivate()
            model.p_charge[t].setub(battery.p_charge_max)
            model.p_discharge[t].setub(battery.p_discharge_max)
            model.u[t].fix(0.0)
        elif act == "idle":
            model.u[t].fix(float(fallback_u))  # negative-priced idle: keep it clamped
        else:
            model.u[t].fix(1.0 if act == "charge" else 0.0)

    model.dual = pyo.Suffix(direction=pyo.Suffix.IMPORT)
    opt = pyo.SolverFactory(solver)
    for key, val in _HIGHS_TOLERANCES.items():
        opt.options[key] = val
    results = opt.solve(model)
    if results.solver.termination_condition != TerminationCondition.optimal:
        raise DualityError(
            f"fix-and-resolve did not reach optimality: {results.solver.termination_condition}"
        )
    obj = pyo.value(model.revenue)
    if abs(obj - milp_objective) > 1e-6 * max(1.0, abs(milp_objective)):
        raise DualityError(
            f"re-solved objective {obj} != MILP objective {milp_objective}: "
            "the relaxation admitted an action the model forbids (ADR-0023)"
        )
    return [model.dual[model.soc_balance[t]] for t in sorted(model.T)]


def _flat_runs(schedule: Schedule, battery: BatterySpec) -> list[list[int]]:
    """Group periods that share a water value: split where SoC hits a bound.

    Periods t and t+1 are in one run iff SoC at t is strictly interior (mu is then
    flat across them). Mirrors the interior-SoC flatness of the water value.
    """
    e_min, e_max = battery.soc_min * battery.capacity, battery.capacity
    runs: list[list[int]] = []
    cur = [0]
    for t in range(len(schedule.soc) - 1):
        if e_min + 1e-6 < schedule.soc[t] < e_max - 1e-6:
            cur.append(t + 1)
        else:
            runs.append(cur)
            cur = [t + 1]
    runs.append(cur)
    return runs


def _reason(action: str, price: float, lo: float, hi: float, pinned: bool) -> str:
    """Human-readable why. ``lo``/``hi`` are the raw band edges (always defined)."""
    if action == "charge":
        return f"charge: price {price:.2f} at or below the charge threshold {lo:.2f}"
    if action == "discharge":
        return f"discharge: price {price:.2f} at or above the discharge threshold {hi:.2f}"
    if not pinned:  # negative-priced idle, tie-break ambiguous
        empty = "; band empty (not an economic no-trade decision)" if lo > hi else ""
        return f"idle at negative price {price:.2f}: water value tie-break ambiguous{empty}"
    return f"idle: price {price:.2f} inside the no-trade band [{lo:.2f}, {hi:.2f}]"


def explain_schedule(
    prices: Sequence[float],
    battery: BatterySpec,
    *,
    dt: float = 1.0,
    solver: str = "appsi_highs",
) -> Explanation:
    """Solve the dispatch, fix the commitment, re-solve the LP, read the water value.

    Groups periods into flat runs and, when any negative-priced idle (fallback) period
    exists, re-solves that tie-break the other way to mark each run pinned or not (one
    extra LP for the horizon). Bands are reported on pinned runs only. Raises
    ``DualityError`` if a re-solved LP objective does not equal the MILP's (ADR-0023).
    """
    schedule = solve(prices, battery, dt=dt, solver=solver)
    n = len(prices)
    c_deg = battery.degradation.cost_per_mwh if battery.degradation is not None else 0.0
    eta_ch, eta_dis = battery.eta_charge, battery.eta_discharge

    fallback = [t for t in range(n) if _action(schedule, t) == "idle" and prices[t] < 0.0]
    mu = _resolve(prices, battery, dt, schedule, 0, solver, schedule.objective)
    if fallback:
        mu_alt = _resolve(prices, battery, dt, schedule, 1, solver, schedule.objective)
        pinned_t = [abs(mu[t] - mu_alt[t]) < _PIN_TOL for t in range(n)]
    else:
        pinned_t = [True] * n

    # Runs partition the horizon; pinnedness is constant within a run (mu is flat).
    period_run = [0] * n
    runs: list[FlatRun] = []
    for i, members in enumerate(_flat_runs(schedule, battery)):
        pinned = all(pinned_t[t] for t in members)
        runs.append(
            FlatRun(
                periods=tuple(members),
                water_value_eur_mwh=mu[members[0]],
                pinned=pinned,
            )
        )
        for t in members:
            period_run[t] = i

    periods: list[PeriodExplanation] = []
    for t in range(n):
        act = _action(schedule, t)
        pinned = runs[period_run[t]].pinned
        # Raw band edges from the water value; reported only where the run is pinned.
        lo_raw = eta_ch * (mu[t] - c_deg)
        hi_raw = (mu[t] + c_deg) / eta_dis
        if act == "charge":
            breakeven = lo_raw - prices[t]
        elif act == "discharge":
            breakeven = prices[t] - hi_raw
        else:
            breakeven = None
        tau = eta_ch * schedule.p_charge[t] * dt + schedule.p_discharge[t] / eta_dis * dt
        periods.append(
            PeriodExplanation(
                action=act,
                price_eur_mwh=prices[t],
                water_value_eur_mwh=mu[t],
                degradation_cost_eur=c_deg * tau,
                run=period_run[t],
                reason=_reason(act, prices[t], lo_raw, hi_raw, pinned),
                band_low_eur_mwh=lo_raw if pinned else None,
                band_high_eur_mwh=hi_raw if pinned else None,
                breakeven_slippage_eur_mwh=breakeven,
            )
        )

    return Explanation(schedule=schedule, runs=runs, periods=periods)
