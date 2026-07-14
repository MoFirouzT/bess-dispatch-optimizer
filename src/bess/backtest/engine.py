"""Walk-forward backtest engine — runs the three baselines over a price series,
concatenates their schedules, and reports the metrics + correctness quantities.

Math: ``docs/formulation.md`` § "R1.4 — Backtest semantics". Spec:
``docs/specs/R1.4a-backtest.md``. No new optimization math: the engine windows the
series, delegates to the baselines, and assembles the report.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

import pandas as pd

from bess.assets.battery import BatterySpec
from bess.backtest.baselines import greedy_window, solve_window
from bess.optimizer.core import Schedule

HOURS_PER_YEAR = 8760.0


@dataclass(frozen=True)
class BaselineResult:
    """One baseline over the whole series. ``window_sizes`` segments the schedule
    (ceiling = one global window; rolling/greedy = one per decision window)."""

    name: str
    revenue_eur: float
    schedule: Schedule
    window_sizes: list[int]
    solve_seconds: list[float]


@dataclass(frozen=True)
class BacktestReport:
    greedy: BaselineResult
    rolling: BaselineResult
    perfect_foresight: BaselineResult
    pct_of_perfect_foresight: float
    uplift_vs_greedy_eur: float
    annualized_ceiling_per_mwh: float
    mean_daily_spread_eur: float
    constraint_satisfaction: bool


@dataclass(frozen=True)
class DurationResult:
    """One backtest at a given storage duration (energy-to-power ratio, hours).

    Reporting only (ADR-0022): the optimizer is scale-invariant in the ratings, so
    each ``report`` is a plain ``run_backtest`` at ``capacity = power * duration_h``.
    """

    duration_h: float
    capacity_mwh: float
    report: BacktestReport

    @property
    def pct_of_perfect_foresight(self) -> float:
        return self.report.pct_of_perfect_foresight

    @property
    def annualized_ceiling_per_mwh(self) -> float:
        return self.report.annualized_ceiling_per_mwh


def _to_windows(prices: Sequence[float] | pd.Series, window: int | str) -> list[list[float]]:
    """Split into decision windows. pandas Series + offset string ⇒ calendar-day
    grouping (UTC); plain sequence + int ⇒ fixed period count."""
    if isinstance(prices, pd.Series):
        if not isinstance(window, str):
            raise TypeError("with a pandas Series, `window` must be an offset string (e.g. '1D')")
        index = cast(pd.DatetimeIndex, prices.index)
        return [grp.astype(float).tolist() for _, grp in prices.groupby(index.normalize())]
    if not isinstance(window, int) or window < 1:
        raise TypeError("with a sequence, `window` must be a positive int (periods per window)")
    vals = [float(p) for p in prices]
    return [vals[i : i + window] for i in range(0, len(vals), window)]


def _concat(schedules: list[Schedule]) -> Schedule:
    p_ch: list[float] = []
    p_dis: list[float] = []
    soc: list[float] = []
    obj = 0.0
    for s in schedules:
        p_ch += s.p_charge
        p_dis += s.p_discharge
        soc += s.soc
        obj += s.objective
    return Schedule(p_ch, p_dis, soc, obj)


def _flat(prices: Sequence[float] | pd.Series) -> list[float]:
    if isinstance(prices, pd.Series):
        return [float(p) for p in prices.tolist()]
    return [float(p) for p in prices]


def run_backtest(
    prices: Sequence[float] | pd.Series,
    spec: BatterySpec,
    dt: float = 1.0,
    *,
    window: int | str = "1D",
    greedy_charge_pct: float = 20.0,
    greedy_discharge_pct: float = 80.0,
    percentile_method: str = "linear",
) -> BacktestReport:
    """Run greedy / rolling / perfect-foresight over ``prices`` and report metrics."""
    windows = _to_windows(prices, window)
    flat = _flat(prices)

    # Perfect-foresight ceiling: one full-horizon solve (SoC free across windows).
    ceil_sched, ceil_t = solve_window(flat, spec, dt)
    ceiling = BaselineResult(
        "perfect_foresight", ceil_sched.objective, ceil_sched, [len(flat)], [ceil_t]
    )

    # Rolling: per-window solves, each empty→empty.
    roll_scheds, roll_times = [], []
    for w in windows:
        s, secs = solve_window(w, spec, dt)
        roll_scheds.append(s)
        roll_times.append(secs)
    roll_sched = _concat(roll_scheds)
    rolling = BaselineResult(
        "rolling", roll_sched.objective, roll_sched, [len(w) for w in windows], roll_times
    )

    # Greedy floor: per-window percentile heuristic.
    greedy_scheds = [
        greedy_window(
            w,
            spec,
            dt,
            charge_pct=greedy_charge_pct,
            discharge_pct=greedy_discharge_pct,
            method=percentile_method,
        )
        for w in windows
    ]
    greedy_sched = _concat(greedy_scheds)
    greedy = BaselineResult(
        "greedy", greedy_sched.objective, greedy_sched, [len(w) for w in windows], []
    )

    # Metrics.
    v_star = ceiling.revenue_eur
    pct = rolling.revenue_eur / v_star if v_star > 1e-12 else 0.0
    e_usable = spec.capacity * (1.0 - spec.soc_min)
    years = (len(flat) * dt) / HOURS_PER_YEAR
    annualized = v_star / e_usable / years if (e_usable > 0 and years > 0) else 0.0
    spreads = [max(w) - min(w) for w in windows if w]
    mean_spread = sum(spreads) / len(spreads) if spreads else 0.0
    ok = all(_satisfies(r, spec, dt) for r in (greedy, rolling, ceiling))

    return BacktestReport(
        greedy=greedy,
        rolling=rolling,
        perfect_foresight=ceiling,
        pct_of_perfect_foresight=pct,
        uplift_vs_greedy_eur=rolling.revenue_eur - greedy.revenue_eur,
        annualized_ceiling_per_mwh=annualized,
        mean_daily_spread_eur=mean_spread,
        constraint_satisfaction=ok,
    )


def _satisfies(result: BaselineResult, spec: BatterySpec, dt: float, eps: float = 1e-6) -> bool:
    """Physical-feasibility check per the result's own segmentation."""
    e_min = spec.soc_min * spec.capacity
    s = result.schedule
    start = 0
    for size in result.window_sizes:
        prev = e_min
        for t in range(start, start + size):
            if not (-eps <= s.p_charge[t] <= spec.p_charge_max + eps):
                return False
            if not (-eps <= s.p_discharge[t] <= spec.p_discharge_max + eps):
                return False
            if s.p_charge[t] > eps and s.p_discharge[t] > eps:
                return False
            if not (e_min - eps <= s.soc[t] <= spec.capacity + eps):
                return False
            expected = (
                prev
                + spec.eta_charge * s.p_charge[t] * dt
                - s.p_discharge[t] / spec.eta_discharge * dt
            )
            if abs(s.soc[t] - expected) > eps:
                return False
            prev = s.soc[t]
        if abs(prev - e_min) > eps:
            return False
        start += size
    return True


def run_duration_sweep(
    prices: Sequence[float] | pd.Series,
    base_spec: BatterySpec,
    dt: float = 1.0,
    *,
    durations: Sequence[float] = (1.0, 2.0, 4.0),
    **backtest_kwargs: object,
) -> list[DurationResult]:
    """Run ``run_backtest`` across storage durations, holding power fixed (ADR-0022).

    Storage duration is the energy-to-power ratio in hours; for each ``d`` the
    capacity is ``power * d`` where ``power = base_spec.p_discharge_max`` (the
    per-unit SoC fields are duration-independent, so they carry over unchanged).
    The optimizer is scale-invariant in the ratings, so each report is a plain
    backtest; this only tabulates them so the capture ratio and per-MWh economics
    are reported across durations rather than for a single asset. Correctness at
    ``capacity != 1`` is covered by the backtest property tests, not re-asserted here.
    """
    power = base_spec.p_discharge_max
    return [
        DurationResult(
            duration_h=float(d),
            capacity_mwh=power * float(d),
            report=run_backtest(
                prices,
                base_spec.model_copy(update={"capacity": power * float(d)}),
                dt,
                **backtest_kwargs,  # type: ignore[arg-type]
            ),
        )
        for d in durations
    ]
