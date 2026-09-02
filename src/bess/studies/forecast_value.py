"""Forecast value: does a better forecast convert into dispatch euros? (R2.5)

Formulation: ``docs/formulation-evaluation.md`` § R2.5; spec:
``docs/specs/value-evaluation.md``. Feeds the same two-stage dispatch two
scenario sets that differ only in the forecast behind them (conformal vs.
seasonal-naive) and compares realized-path profit.
:func:`forecast_value_from_sets` is the token-free core and carries the
golden/property gates; the wrappers own the forecaster plumbing and need the
optional ``forecast`` dependency group.

Not sign-asserted: a naive forecast that happens to dispatch better is a finding,
not a failure. The measured distribution came out centred on zero.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from bess.assets.battery import BatterySpec
from bess.scenarios import ScenarioSet
from bess.stochastic.twostage import solve_stochastic
from bess.stochastic.vss import _net_to_pair
from bess.studies.windows import _HOURS, _as_utc_days, _complete_day_matrix, window_seed

# The forecaster's week-scale lags plus its train/calibration split need this much
# history before the first window that can be scored.
_MIN_LAG_DAYS = 9


@dataclass(frozen=True)
class ForecastValue:
    """The forecast-value comparison on one window (EUR)."""

    profit_conformal_eur: float
    profit_naive_eur: float
    fv_eur: float  # profit_conformal − profit_naive; reported, not sign-asserted


@dataclass(frozen=True)
class WindowFV:
    """One window's forecast-value result (EUR; spec amendment 2026-07-22)."""

    window_start: pd.Timestamp
    profit_conformal_eur: float
    profit_naive_eur: float
    fv_eur: float  # per-window; the distribution's center is the finding


def forecast_value_from_sets(
    conformal: ScenarioSet,
    naive: ScenarioSet,
    realized: Any,
    battery: BatterySpec,
    *,
    dt: float = 1.0,
    rho: float = 0.5,
) -> ForecastValue:
    """Score two scenario sets by the realized-path value of their commitments.

    The token-free core of the forecast-value baseline: for each set, fit the
    risk-neutral two-stage commitment, then score it fixed on the realized path
    with the day-ahead leg settling at that set's own mean (each forecaster is
    held to the price basis it believed in). Antisymmetric in its two inputs and
    exactly null when they are identical.
    """
    realized_path = np.asarray(realized, dtype=float)

    def score(train: ScenarioSet) -> float:
        commitment = _net_to_pair(solve_stochastic(train, battery, dt=dt, rho=rho).g_da)
        evaluation = ScenarioSet(
            paths=realized_path[None, :], probs=np.array([1.0]), index=train.index
        )
        train_mean = np.asarray(train.probs) @ np.asarray(train.paths)
        return solve_stochastic(
            evaluation, battery, dt=dt, rho=rho, fix_da=commitment, pi_da=train_mean
        ).expected_profit

    profit_conformal = score(conformal)
    profit_naive = score(naive)
    return ForecastValue(profit_conformal, profit_naive, profit_conformal - profit_naive)


def fv_windows_from_sets(
    items: list[tuple[pd.Timestamp, ScenarioSet, ScenarioSet, Any]],
    battery: BatterySpec,
    *,
    dt: float = 1.0,
    rho: float = 0.5,
) -> list[WindowFV]:
    """Score a sequence of (start, conformal set, naive set, realized) windows.

    The token-free loop core of the FV distribution (spec amendment 2026-07-22):
    each item is scored by :func:`forecast_value_from_sets` unchanged, so the
    distribution machinery adds no value of its own. One :class:`WindowFV` per
    item, in order.
    """
    out: list[WindowFV] = []
    for start, conformal, naive, realized in items:
        r = forecast_value_from_sets(conformal, naive, realized, battery, dt=dt, rho=rho)
        out.append(WindowFV(start, r.profit_conformal_eur, r.profit_naive_eur, r.fv_eur))
    return out


def fv_across_windows(
    prices: pd.Series,
    battery: BatterySpec,
    *,
    history_days: int = 28,
    n_scenarios: int = 30,
    rho: float = 0.5,
    seed: int = 0,
    refit_days: int = 7,
    only_days: Sequence[pd.Timestamp] | pd.DatetimeIndex | None = None,
) -> list[WindowFV]:
    """The forecast-value distribution over every UTC-day window that can be scored.

    The per-window form of :func:`forecast_value` (spec amendment 2026-07-22),
    under the R2.1 walk-forward discipline: the forecaster is refit on data
    strictly before each ``refit_days`` block of windows, and each window's
    residual histories use days strictly before it. Per-window scenario seeds
    derive from ``seed`` plus the window ordinal (deterministic, distinct).
    Windows either predictor cannot fully cover are skipped, not padded.
    Needs the optional ``forecast`` group.
    """
    try:
        from bess.forecaster.forecast import IntervalForecast, PriceForecaster
    except ImportError as exc:  # pragma: no cover - exercised only without the group
        raise ImportError(
            "fv_across_windows needs the forecast group: `uv sync --group forecast`"
        ) from exc
    from bess.forecaster.evaluate import seasonal_naive
    from bess.scenarios import generate_scenarios

    if refit_days < 1:
        raise ValueError(f"refit_days must be >= 1; got {refit_days}")
    starts, mat = _complete_day_matrix(prices)
    first = max(history_days, _MIN_LAG_DAYS)
    if len(starts) <= first:
        raise ValueError(f"need more than {first} complete days; got {len(starts)}")
    idx_norm = pd.DatetimeIndex(prices.index).normalize()
    naive_series = seasonal_naive(prices)
    naive_days = pd.DatetimeIndex(naive_series.index).normalize()

    def complete_path(
        series: pd.Series, days: pd.DatetimeIndex, day: pd.Timestamp
    ) -> np.ndarray | None:
        path = series[days == day].to_numpy(dtype=float)
        return path if len(path) == _HOURS else None

    def residuals_before(series: pd.Series, days: pd.DatetimeIndex, upto: int) -> np.ndarray | None:
        rows = []
        for j in range(upto - 1, -1, -1):
            pred = complete_path(series, days, starts[j])
            if pred is not None:
                rows.append(mat[j] - pred)
            if len(rows) == history_days:
                break
        return np.asarray(rows) if len(rows) >= 2 else None

    wanted = None if only_days is None else set(_as_utc_days(only_days))
    items: list[tuple[pd.Timestamp, ScenarioSet, ScenarioSet, Any]] = []
    for block_start in range(first, len(starts), refit_days):
        block = range(block_start, min(block_start + refit_days, len(starts)))
        if wanted is not None and not any(starts[i] in wanted for i in block):
            continue  # no selected window here, so its refit would be discarded
        # Walk-forward: fit strictly before the block, predict through its end.
        forecaster = PriceForecaster(random_state=seed)
        forecaster.fit(prices[idx_norm < starts[block_start]])
        fc = forecaster.predict_interval(prices[idx_norm <= starts[block[-1]]])
        fc_days = pd.DatetimeIndex(fc.point.index).normalize()
        for i in block:
            day = starts[i]
            if wanted is not None and day not in wanted:
                continue
            point = complete_path(fc.point, fc_days, day)
            lower = complete_path(fc.lower, fc_days, day)
            upper = complete_path(fc.upper, fc_days, day)
            npath = complete_path(naive_series, naive_days, day)
            c_res = residuals_before(fc.point, fc_days, i)
            n_res = residuals_before(naive_series, naive_days, i)
            if point is None or lower is None or upper is None or npath is None:
                continue  # a predictor does not fully cover this window
            if c_res is None or n_res is None:
                continue  # not enough covered history for a residual bootstrap
            window_index = pd.date_range(day, periods=_HOURS, freq="h")
            conf_fc = IntervalForecast(
                point=pd.Series(point, index=window_index),
                lower=pd.Series(lower, index=window_index),
                upper=pd.Series(upper, index=window_index),
                confidence_level=fc.confidence_level,
            )
            naive_path = pd.Series(npath, index=window_index)
            naive_fc = IntervalForecast(
                point=naive_path, lower=naive_path, upper=naive_path,
                confidence_level=fc.confidence_level,
            )  # fmt: skip
            s = window_seed(seed, day)
            conf_set = generate_scenarios(conf_fc, c_res, n=n_scenarios, seed=s)
            naive_set = generate_scenarios(naive_fc, n_res, n=n_scenarios, seed=s)
            items.append((day, conf_set, naive_set, mat[i]))
    return fv_windows_from_sets(items, battery, rho=rho)


def forecast_value(
    prices: pd.Series,
    battery: BatterySpec,
    *,
    history_days: int = 28,
    n_scenarios: int = 30,
    rho: float = 0.5,
    seed: int = 0,
) -> ForecastValue:
    """The forecast-value baseline on the last complete day of ``prices``.

    Fits the R2.1 conformal forecaster on everything strictly before that day,
    builds two R2.2 scenario sets differing only in the forecast feeding the
    residual-path bootstrap (conformal point + its residual history vs.
    seasonal-naive point + its own residual history), and hands both to
    :func:`forecast_value_from_sets`. Needs the optional ``forecast`` group.
    """
    try:
        from bess.forecaster.forecast import IntervalForecast, PriceForecaster
    except ImportError as exc:  # pragma: no cover - exercised only without the group
        raise ImportError(
            "forecast_value needs the forecast group: `uv sync --group forecast`"
        ) from exc
    from bess.forecaster.evaluate import seasonal_naive
    from bess.scenarios import generate_scenarios

    starts, mat = _complete_day_matrix(prices)
    if len(starts) <= history_days + 8:  # +8: the forecaster's week-scale lags need history
        raise ValueError(
            f"need more than {history_days + 8} complete days for history + lags; got {len(starts)}"
        )
    eval_day = starts[-1]
    realized = mat[-1]
    idx = pd.DatetimeIndex(prices.index)

    forecaster = PriceForecaster(random_state=seed)
    forecaster.fit(prices[idx.normalize() < eval_day])
    fc = forecaster.predict_interval(prices)
    fc_days = pd.DatetimeIndex(fc.point.index).normalize()

    naive_series = seasonal_naive(prices)
    naive_days = pd.DatetimeIndex(naive_series.index).normalize()

    def day_path(series: pd.Series, days: pd.DatetimeIndex, day: pd.Timestamp) -> np.ndarray:
        path = series[days == day].to_numpy(dtype=float)
        if len(path) != _HOURS:
            raise ValueError(f"no complete prediction for {day.date()} (got {len(path)} hours)")
        return path

    # Whole-day residual history (actual − prediction) over the newest fully-covered
    # days strictly before the window: the R2.2 bootstrap input, per predictor.
    def residual_history(series: pd.Series, days: pd.DatetimeIndex) -> np.ndarray:
        rows = []
        for i in range(len(starts) - 2, -1, -1):
            pred = series[days == starts[i]]
            if len(pred) == _HOURS:
                rows.append(mat[i] - pred.to_numpy(dtype=float))
            if len(rows) == history_days:
                break
        if len(rows) < 2:
            raise ValueError("not enough covered history days to form a residual history")
        return np.asarray(rows)

    window_index = pd.date_range(eval_day, periods=_HOURS, freq="h")
    conf_forecast = IntervalForecast(
        point=pd.Series(day_path(fc.point, fc_days, eval_day), index=window_index),
        lower=pd.Series(day_path(fc.lower, fc_days, eval_day), index=window_index),
        upper=pd.Series(day_path(fc.upper, fc_days, eval_day), index=window_index),
        confidence_level=fc.confidence_level,
    )
    naive_path = pd.Series(day_path(naive_series, naive_days, eval_day), index=window_index)
    # A degenerate (point) interval: only `.point` feeds the bootstrap; the level
    # is carried for symmetry with the conformal side, not used.
    naive_forecast = IntervalForecast(
        point=naive_path, lower=naive_path, upper=naive_path,
        confidence_level=fc.confidence_level,
    )  # fmt: skip

    conf_set = generate_scenarios(
        conf_forecast, residual_history(fc.point, fc_days), n=n_scenarios, seed=seed
    )
    naive_set = generate_scenarios(
        naive_forecast, residual_history(naive_series, naive_days), n=n_scenarios, seed=seed
    )
    return forecast_value_from_sets(conf_set, naive_set, realized, battery, rho=rho)
