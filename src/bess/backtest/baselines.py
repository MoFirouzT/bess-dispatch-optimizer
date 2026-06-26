"""The three backtest baselines, each over a single window.

Math: ``docs/formulation.md`` § "R1.4 — Backtest semantics". Spec:
``docs/specs/R1.4a-backtest.md``. ``perfect_foresight`` (full horizon) and
``rolling`` (per window) are solves of the existing R1.1/R1.2 optimizer with
**empty** SoC endpoints; ``greedy`` is a feasibility-preserving percentile rule.

``backtest`` imports ``optimizer``/``assets`` but not the serving chain
(import-linter).
"""

from __future__ import annotations

import time
from collections.abc import Sequence

import numpy as np

from bess.assets.battery import BatterySpec
from bess.optimizer.core import Schedule, solve


def _empty(spec: BatterySpec) -> BatterySpec:
    """Same asset, forced to start and end **empty** (at ``soc_min``)."""
    return spec.model_copy(update={"soc_initial": spec.soc_min, "soc_terminal": spec.soc_min})


def solve_window(prices: Sequence[float], spec: BatterySpec, dt: float) -> tuple[Schedule, float]:
    """Optimal dispatch over one price block, empty→empty. Returns (schedule, seconds)."""
    t0 = time.perf_counter()
    sched = solve(prices, _empty(spec), dt=dt)
    return sched, time.perf_counter() - t0


def _trajectory(
    p_ch: list[float], p_dis: list[float], spec: BatterySpec, dt: float, e_start: float
) -> list[float]:
    soc, out = e_start, []
    for pc, pd_ in zip(p_ch, p_dis, strict=True):
        soc = soc + spec.eta_charge * pc * dt - pd_ / spec.eta_discharge * dt
        out.append(soc)
    return out


def greedy_window(
    prices: Sequence[float],
    spec: BatterySpec,
    dt: float,
    *,
    charge_pct: float,
    discharge_pct: float,
    method: str = "linear",
) -> Schedule:
    """Percentile rule: charge below ``charge_pct``, discharge above ``discharge_pct``.

    Feasibility-preserving and **ends empty** — a charge is capped so the trailing
    periods can always discharge it, and any remainder is liquidated from the end
    backward. A valid (suboptimal) floor; it ignores the round-trip breakeven, so
    it can trade at a loss.
    """
    m = len(prices)
    e_min = spec.soc_min * spec.capacity
    e_max = spec.capacity
    p_ch = [0.0] * m
    p_dis = [0.0] * m
    if m == 0:
        return Schedule([], [], [], 0.0)

    p_lo = float(np.percentile(prices, charge_pct, method=method))
    p_hi = float(np.percentile(prices, discharge_pct, method=method))
    # Most SoC one trailing period can remove (storage-side) — the liquidation budget.
    max_removal = spec.p_discharge_max * dt / spec.eta_discharge

    soc = e_min
    for t in range(m):
        price = prices[t]
        later_high = any(prices[u] >= p_hi for u in range(t + 1, m))
        if price <= p_lo and later_high and soc < e_max - 1e-12:
            # Cap stored energy so the (m-1-t) trailing periods can fully discharge it.
            max_soc_now = min(e_max, e_min + (m - 1 - t) * max_removal)
            headroom = max(0.0, max_soc_now - soc)
            pc = min(spec.p_charge_max, headroom / (spec.eta_charge * dt))
            if pc > 1e-12:
                p_ch[t] = pc
                soc += spec.eta_charge * pc * dt
        elif price >= p_hi and soc > e_min + 1e-12:
            avail = spec.eta_discharge * (soc - e_min) / dt
            pd_ = min(spec.p_discharge_max, avail)
            if pd_ > 1e-12:
                p_dis[t] = pd_
                soc -= pd_ / spec.eta_discharge * dt

    _liquidate(p_ch, p_dis, spec, dt, e_min)

    soc_list = _trajectory(p_ch, p_dis, spec, dt, e_min)
    obj = sum(prices[t] * dt * (p_dis[t] - p_ch[t]) for t in range(m))
    return Schedule(p_ch, p_dis, soc_list, obj)


def _liquidate(
    p_ch: list[float], p_dis: list[float], spec: BatterySpec, dt: float, e_min: float
) -> None:
    """Force-discharge any leftover SoC so the window ends empty, keeping SoC ≥ e_min
    throughout. Recomputes the trajectory each pass (windows are short)."""
    m = len(p_ch)
    for _ in range(m + 1):
        soc = _trajectory(p_ch, p_dis, spec, dt, e_min)
        leftover = soc[-1] - e_min if soc else 0.0
        if leftover <= 1e-9:
            return
        progressed = False
        for t in range(m - 1, -1, -1):
            if p_ch[t] > 0.0:
                continue
            spare = spec.p_discharge_max - p_dis[t]
            if spare <= 1e-12:
                continue
            # Adding discharge at t lowers SoC at t..end uniformly; keep the min ≥ e_min.
            min_future = min(soc[t:])
            room = spec.eta_discharge * (min_future - e_min) / dt
            add = min(spare, room, spec.eta_discharge * leftover / dt)
            if add > 1e-12:
                p_dis[t] += add
                progressed = True
                break
        if not progressed:  # the charge budget guarantees this never triggers
            return
