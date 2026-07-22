"""Value evaluation studies over the two-stage program (R2.5).

Formulation: ``docs/formulation.md`` § R2.5; spec:
``docs/specs/R2.5-value-evaluation.md``. Two protocols, both pure evaluation
(no optimizer change):

- :func:`vss_across_windows` — the per-window out-of-sample VSS: repeat the
  ADR-0021 measurement over arbitrary UTC-day windows of a real price series,
  so the reported object is a *distribution* (is VSS > 0 a property of the
  market, or of R2.3's designed instance?);
- :func:`forecast_value` — the forecast-value baseline: the same two-stage
  dispatch fed conformal vs. seasonal-naive scenarios, compared in euros on the
  realized path. :func:`forecast_value_from_sets` is its token-free core and
  carries the golden/property gates; the wrapper owns the forecaster plumbing
  and needs the optional ``forecast`` dependency group.

Neither quantity is sign-asserted: a negative window (or a naive forecast that
happens to dispatch better) is a finding, not a failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from bess.assets.battery import BatterySpec
from bess.scenarios import ScenarioSet
from bess.stochastic.twostage import solve_stochastic
from bess.stochastic.vss import _net_to_pair, out_of_sample_vss

_HOURS = 24  # a window is one UTC day of hourly prices (spec § Parameters)


@dataclass(frozen=True)
class WindowVSS:
    """One window's out-of-sample decision-value result (EUR)."""

    window_start: pd.Timestamp
    rp_oos: float  # held-out score of the stochastic (RP) commitment
    eev_oos: float  # held-out score of the mean-value (EV) commitment
    vss_oos: float  # rp_oos − eev_oos; carries no sign guarantee (ADR-0021)


@dataclass(frozen=True)
class ForecastValue:
    """The forecast-value comparison on one window (EUR)."""

    profit_conformal_eur: float
    profit_naive_eur: float
    fv_eur: float  # profit_conformal − profit_naive; reported, not sign-asserted


def _complete_day_matrix(prices: pd.Series) -> tuple[list[pd.Timestamp], np.ndarray]:
    """Split an hourly series into complete UTC days: (day starts, (D, 24) matrix).

    Incomplete days (a truncated head/tail, a DST-affected local grouping fed in
    by mistake) are dropped, not padded: a window is exactly one full day.
    """
    s = prices.sort_index()
    idx = pd.DatetimeIndex(s.index)
    starts: list[pd.Timestamp] = []
    rows: list[np.ndarray] = []
    for day, chunk in s.groupby(idx.normalize()):
        if len(chunk) == _HOURS:
            starts.append(day)
            rows.append(chunk.to_numpy(dtype=float))
    return starts, np.asarray(rows)


def window_sets(
    prices: pd.Series,
    *,
    history_days: int = 28,
    n_scenarios: int = 30,
    seed: int = 0,
) -> list[tuple[pd.Timestamp, ScenarioSet, ScenarioSet]]:
    """Build each window's (start, training set, evaluation set) triple.

    For every complete UTC day with ``history_days`` complete days strictly
    before it: the training set is ``n_scenarios`` equiprobable day-paths drawn
    with replacement from those trailing days (an empirical bootstrap over
    recent day shapes; the §R1.4 information set, so nothing at or after the
    window enters), and the evaluation set is the window's own realized path
    (S = 1). Deterministic under ``seed``.
    """
    if history_days < 1:
        raise ValueError(f"history_days must be >= 1; got {history_days}")
    if n_scenarios < 1:
        raise ValueError(f"n_scenarios must be >= 1; got {n_scenarios}")
    starts, mat = _complete_day_matrix(prices)
    rng = np.random.default_rng(seed)
    out: list[tuple[pd.Timestamp, ScenarioSet, ScenarioSet]] = []
    for i in range(history_days, len(starts)):
        index = pd.date_range(starts[i], periods=_HOURS, freq="h")
        draws = rng.integers(0, history_days, size=n_scenarios)
        train = ScenarioSet(
            paths=mat[i - history_days : i][draws],
            probs=np.full(n_scenarios, 1.0 / n_scenarios),
            index=index,
        )
        evaluation = ScenarioSet(paths=mat[i][None, :], probs=np.array([1.0]), index=index)
        out.append((starts[i], train, evaluation))
    return out


def vss_across_windows(
    prices: pd.Series,
    battery: BatterySpec,
    *,
    history_days: int = 28,
    n_scenarios: int = 30,
    rho: float = 0.5,
    seed: int = 0,
) -> list[WindowVSS]:
    """The per-window out-of-sample VSS distribution (formulation §R2.5).

    Each window repeats the ADR-0021 protocol: fit the RP and EV commitments on
    the window's training scenarios, score each fixed (with optimal within-budget
    recourse, the day-ahead leg settling at the training mean) on the realized
    path. The caller reports the distribution; no single-number summary is
    computed here by design.
    """
    results: list[WindowVSS] = []
    for start, train, evaluation in window_sets(
        prices, history_days=history_days, n_scenarios=n_scenarios, seed=seed
    ):
        r = out_of_sample_vss(train, evaluation, battery, rho=rho)
        results.append(WindowVSS(start, r.rp_oos, r.eev_oos, r.vss_oos))
    return results


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
