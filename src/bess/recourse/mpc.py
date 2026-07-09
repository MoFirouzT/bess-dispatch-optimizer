"""Intraday recourse as a receding-horizon (MPC) policy (R2.3).

Formulation: ``docs/formulation.md`` § R2.3, ADR-0021. Executes the committed
action, then re-solves the remaining horizon at the updated realised prices,
carrying SoC as the linking state. The plant model is the R1.1 SoC dynamics; the
disturbance is the price forecast. Because each sub-problem re-plans to the same
terminal SoC, feasibility is preserved by construction (the committed action is
always the head of a feasible-to-terminal plan). This module imports
``optimizer`` / ``assets`` only (import-linter core chain).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from bess.assets.battery import BatterySpec
from bess.optimizer.core import solve


@dataclass
class RecourseResult:
    """Realised outcome of the receding-horizon policy on one price path."""

    value: float  # realised revenue at the executed dispatch (EUR)
    p_charge: list[float]  # committed grid-side charge power per period (MW)
    p_discharge: list[float]  # committed grid-side discharge power per period (MW)
    soc: list[float]  # SoC after each period (MWh)


def rolling_recourse(
    realized: Sequence[float] | np.ndarray,
    battery: BatterySpec,
    *,
    dt: float = 1.0,
    forecast: Sequence[float] | np.ndarray | None = None,
    warm_start: bool = True,
) -> RecourseResult:
    """Simulate the MPC recourse against a realised price path.

    At each step the current price is known (``realized[t]``) and the remaining
    horizon uses ``forecast`` (``None`` ⇒ perfect foresight, i.e. the realised
    path). The first action of each re-solve is committed and settled at the
    realised price; SoC is carried into the next window. ``warm_start`` is a hook
    for seeding each re-solve from the previous window (a latency optimisation);
    it does not change the computed policy.
    """
    _ = warm_start  # reserved: warm-start is a solver-latency optimisation only
    realized = np.asarray(realized, dtype=float)
    horizon = len(realized)
    future_prices = realized if forecast is None else np.asarray(forecast, dtype=float)

    carried_pu = battery.soc_initial  # per-unit SoC carried across windows
    p_charge: list[float] = []
    p_discharge: list[float] = []
    soc: list[float] = []
    value = 0.0

    for t in range(horizon):
        # Remaining horizon: current price known, the rest forecast.
        window_prices = np.concatenate([[realized[t]], future_prices[t + 1 :]])
        # Clamp float noise so the frozen-spec SoC-window validation does not trip.
        carried_pu = min(max(carried_pu, battery.soc_min), 1.0)
        sub = battery.model_copy(update={"soc_initial": carried_pu})
        sched = solve(list(window_prices), sub, dt)

        pc, pd_ = sched.p_charge[0], sched.p_discharge[0]
        p_charge.append(pc)
        p_discharge.append(pd_)
        value += float(realized[t]) * dt * (pd_ - pc)

        soc_mwh = (
            carried_pu * battery.capacity
            + battery.eta_charge * pc * dt
            - pd_ / battery.eta_discharge * dt
        )
        soc.append(soc_mwh)
        carried_pu = soc_mwh / battery.capacity

    return RecourseResult(value=value, p_charge=p_charge, p_discharge=p_discharge, soc=soc)
