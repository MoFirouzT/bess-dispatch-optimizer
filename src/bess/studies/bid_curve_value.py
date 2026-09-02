"""Bid-curve value: does a price-contingent commitment beat a blind schedule? (R2.6)

Spec: ``docs/specs/bid-curves.md``; formulation:
``docs/formulation-uncertainty.md`` § R2.6 (evaluation semantics). Compares a
monotone (price, quantity) curve resolved at the realized clearing price against a
single scalar schedule, both fitted on the same training set and scored identically.

Not sign-asserted; the measured value was a null. The quantity that was not null
is the **delivery gap**, reported beside each profit: volume promised and not
delivered, which imbalance settlement would price and this study does not.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from bess.assets.battery import BatterySpec
from bess.scenarios import ScenarioSet
from bess.stochastic.twostage import curve_response, solve_stochastic
from bess.studies.windows import (
    _HOURS,
    _as_utc_days,
    _complete_day_matrix,
    _MeanForecast,
    window_seed,
)


@dataclass(frozen=True)
class BidCurveValue:
    """The curve-vs-scalar comparison on one window (EUR, MWh)."""

    profit_curve_eur: float
    profit_scalar_eur: float
    bcv_eur: float  # profit_curve − profit_scalar; reported, not sign-asserted
    delivery_gap_curve_mwh: float  # Σ_t |g_t − g^DA_t|, the unpriced imbalance (R3.1)
    delivery_gap_scalar_mwh: float


@dataclass(frozen=True)
class WindowBCV:
    """One window's bid-curve-value result (EUR, MWh; R2.6)."""

    window_start: pd.Timestamp
    profit_curve_eur: float
    profit_scalar_eur: float
    bcv_eur: float  # per-window; the distribution's center is the finding
    delivery_gap_curve_mwh: float
    delivery_gap_scalar_mwh: float


def bid_curve_value_from_sets(
    train: ScenarioSet,
    realized: Any,
    battery: BatterySpec,
    *,
    dt: float = 1.0,
    rho: float = 0.5,
) -> BidCurveValue:
    """Realized-path value of a bid-curve commitment minus a scalar commitment.

    The token-free core of the R2.6 study. Both commitments are fitted on the *same*
    training set (the only difference is ``bid_curve``), the curve is resolved at the
    realized clearing prices, and both are scored the same way: as quantity
    obligations entering the recourse budget, with the recourse dispatch carrying the
    R1.1 physics (formulation-uncertainty § R2.6). Scoring them identically is what makes the
    difference attributable to contingency rather than to the evaluation.

    The delivery gap ``Σ_t |g_t − g^DA_t|`` is reported beside each profit: it is the
    volume promised and not delivered, which imbalance settlement would charge for
    (R3.1) and this study does not price.
    """
    realized_path = np.asarray(realized, dtype=float)
    evaluation = ScenarioSet(paths=realized_path[None, :], probs=np.array([1.0]), index=train.index)

    def score(obligation: list[float]) -> tuple[float, float]:
        solved = solve_stochastic(evaluation, battery, dt=dt, rho=rho, commitment=obligation)
        gap = float(np.abs(np.asarray(solved.recourse[0]) - np.asarray(obligation)).sum() * dt)
        return solved.expected_profit, gap

    curve_fit = solve_stochastic(train, battery, dt=dt, rho=rho, bid_curve=True)
    scalar_fit = solve_stochastic(train, battery, dt=dt, rho=rho)
    assert curve_fit.curve is not None  # bid_curve=True always populates it

    profit_curve, gap_curve = score(curve_response(curve_fit.curve, realized_path))
    profit_scalar, gap_scalar = score(scalar_fit.g_da)
    return BidCurveValue(
        profit_curve, profit_scalar, profit_curve - profit_scalar, gap_curve, gap_scalar
    )


def bid_curve_value_across_windows(
    prices: pd.Series,
    battery: BatterySpec,
    *,
    history_days: int = 28,
    n_scenarios: int = 10,
    rho: float = 0.5,
    seed: int = 0,
    only_days: Sequence[pd.Timestamp] | pd.DatetimeIndex | None = None,
) -> list[WindowBCV]:
    """Per-window bid-curve value over every UTC-day window that can be scored (token-free).

    Same harness shape as :func:`tail_value_across_windows`: the point forecast is the
    mean of the trailing ``history_days`` days and the residuals are those days minus
    the point, so training data is strictly prior to the window being scored. Windows
    whose evaluation program is infeasible are **skipped, not padded** (at a tight
    ``rho`` an obligation can lie further from every feasible dispatch than the budget
    allows), which keeps a reported distribution honest about what it covers.

    ``n_scenarios`` defaults to 10 rather than the 30 the R2.5/R2.5b studies use: the
    curve program's monotonicity chain couples all commitment branches, so its solve
    cost grows steeply in the scenario count (spec R2.6, decision 4). The reduction is
    a stated approximation of this study, and it costs scenario-set fidelity.

    ``only_days`` restricts scoring to the given delivery days (the R2.7 fold layout);
    it is a filter, so a selected window carries exactly the result it would carry in
    an unfiltered run.
    """
    from bess.scenarios import generate_scenarios

    starts, mat = _complete_day_matrix(prices)
    if len(starts) <= history_days:
        raise ValueError(f"need more than {history_days} complete days; got {len(starts)}")

    wanted = None if only_days is None else set(_as_utc_days(only_days))
    out: list[WindowBCV] = []
    for i in range(history_days, len(starts)):
        if wanted is not None and starts[i] not in wanted:
            continue
        index = pd.date_range(starts[i], periods=_HOURS, freq="h")
        trailing = mat[i - history_days : i]
        point = trailing.mean(axis=0)
        residuals = trailing - point
        fc = _MeanForecast(point=pd.Series(point, index=index, name="point"))
        train = generate_scenarios(fc, residuals, n=n_scenarios, seed=window_seed(seed, starts[i]))
        try:
            r = bid_curve_value_from_sets(train, mat[i], battery, rho=rho)
        except RuntimeError:  # obligation unreachable within the budget on this day
            continue
        out.append(
            WindowBCV(
                starts[i],
                r.profit_curve_eur,
                r.profit_scalar_eur,
                r.bcv_eur,
                r.delivery_gap_curve_mwh,
                r.delivery_gap_scalar_mwh,
            )
        )
    return out
