"""Tail dispatch value: does the scenario tail earn realized euros? (R2.5b)

Spec: ``docs/specs/tail-dispatch-value.md``. Feeds the two-stage program
two scenario sets differing only in whether the R2.2b/R2.2c extreme-value tail is
spliced on, and compares realized-path profit per window. Not sign-asserted; the
measured answer was a null at every recourse budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from bess.assets.battery import BatterySpec
from bess.scenarios import ScenarioSet
from bess.stochastic.twostage import solve_stochastic
from bess.stochastic.vss import _net_to_pair
from bess.studies.windows import _HOURS, _complete_day_matrix, _MeanForecast


@dataclass(frozen=True)
class TailValue:
    """The tail-vs-plain comparison on one window (EUR)."""

    profit_tail_eur: float
    profit_plain_eur: float
    tv_eur: float  # profit_tail − profit_plain; reported, not sign-asserted


@dataclass(frozen=True)
class WindowTV:
    """One window's tail-dispatch-value result (EUR; R2.5b)."""

    window_start: pd.Timestamp
    profit_tail_eur: float
    profit_plain_eur: float
    tv_eur: float  # per-window; the distribution's center is the finding


def tail_value_from_sets(
    tail: ScenarioSet,
    plain: ScenarioSet,
    realized: Any,
    battery: BatterySpec,
    *,
    basis: Any,
    dt: float = 1.0,
    rho: float = 0.5,
) -> TailValue:
    """Realized-path value of the tail-set commitment minus the plain-set commitment.

    The token-free core of the R2.5b study: for each scenario set, fit the risk-neutral
    two-stage commitment, then score it fixed on the realized path with the day-ahead
    leg settling at ``basis``. The study passes ``basis = realized`` (the realized
    day-ahead price), so a commitment that correctly anticipates a realized spike earns
    it and one that anticipates a spike that does not come loses. ``basis`` is passed
    explicitly (not derived from either set), so the metric stays antisymmetric in its
    two inputs and exactly null when they are identical, whatever basis is chosen.
    """
    realized_path = np.asarray(realized, dtype=float)
    basis_path = np.asarray(basis, dtype=float)

    def score(train: ScenarioSet) -> float:
        commitment = _net_to_pair(solve_stochastic(train, battery, dt=dt, rho=rho).g_da)
        evaluation = ScenarioSet(
            paths=realized_path[None, :], probs=np.array([1.0]), index=train.index
        )
        return solve_stochastic(
            evaluation, battery, dt=dt, rho=rho, fix_da=commitment, pi_da=basis_path
        ).expected_profit

    profit_tail = score(tail)
    profit_plain = score(plain)
    return TailValue(profit_tail, profit_plain, profit_tail - profit_plain)


def tail_value_across_windows(
    prices: pd.Series,
    battery: BatterySpec,
    *,
    residual_load: Any | None = None,
    history_days: int = 28,
    n_scenarios: int = 30,
    rho: float = 0.5,
    seed: int = 0,
    threshold_quantile: float = 0.95,
) -> list[WindowTV]:
    """Per-window tail value over every scoreable UTC-day window (token-free).

    For each window: the point is the mean of the trailing ``history_days`` days and
    the residuals are those days minus the point (the R2.2-live construction). A tail
    is fit on the residuals (R2.2c conditional when ``residual_load`` is supplied, else
    R2.2b unconditional), the plain and tail-augmented scenario sets are generated from
    the same residuals and seed, and both commitments are scored on the realized path
    with the day-ahead leg settling at the **realized** day-ahead price (so a commitment
    that correctly anticipates a realized spike earns it, and one that anticipates a
    spike that does not come loses). ``residual_load`` (per-hour, aligned to ``prices``)
    is typically the R2.1c fundamentals series; without it the study runs the
    unconditional tail. No forecast group needed.
    """
    from bess.scenarios import generate_scenarios
    from bess.scenarios.tail import ConditionalTailModel, TailModel

    starts, mat = _complete_day_matrix(prices)
    if len(starts) <= history_days:
        raise ValueError(f"need more than {history_days} complete days; got {len(starts)}")

    rl_mat: np.ndarray | None = None
    if residual_load is not None:
        rl_series = pd.Series(np.asarray(residual_load, dtype=float), index=prices.index)
        rl_starts, rl_mat = _complete_day_matrix(rl_series)
        if rl_starts != starts:
            raise ValueError("residual_load must cover the same complete days as prices")

    out: list[WindowTV] = []
    for i in range(history_days, len(starts)):
        index = pd.date_range(starts[i], periods=_HOURS, freq="h")
        trailing = mat[i - history_days : i]
        point = trailing.mean(axis=0)
        residuals = trailing - point
        fc = _MeanForecast(point=pd.Series(point, index=index, name="point"))

        tail: TailModel | ConditionalTailModel
        covariate: np.ndarray | None
        if rl_mat is not None:
            tail = ConditionalTailModel.fit(
                residuals, rl_mat[i - history_days : i], threshold_quantile=threshold_quantile
            )
            covariate = rl_mat[i]
        else:
            tail = TailModel.fit(residuals, threshold_quantile=threshold_quantile)
            covariate = None

        s = seed + i
        plain_set = generate_scenarios(fc, residuals, n=n_scenarios, seed=s)
        tail_set = generate_scenarios(
            fc, residuals, n=n_scenarios, seed=s, tail=tail, tail_covariate=covariate
        )
        r = tail_value_from_sets(tail_set, plain_set, mat[i], battery, basis=mat[i], rho=rho)
        out.append(WindowTV(starts[i], r.profit_tail_eur, r.profit_plain_eur, r.tv_eur))
    return out
