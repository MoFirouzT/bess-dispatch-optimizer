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


@dataclass(frozen=True)
class WindowFV:
    """One window's forecast-value result (EUR; spec amendment 2026-07-22)."""

    window_start: pd.Timestamp
    profit_conformal_eur: float
    profit_naive_eur: float
    fv_eur: float  # per-window; the distribution's center is the finding


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


# The forecaster's week-scale lags plus its train/calibration split need this much
# history before the first scoreable window.
_MIN_LAG_DAYS = 9


def fv_across_windows(
    prices: pd.Series,
    battery: BatterySpec,
    *,
    history_days: int = 28,
    n_scenarios: int = 30,
    rho: float = 0.5,
    seed: int = 0,
    refit_days: int = 7,
) -> list[WindowFV]:
    """The forecast-value distribution over every scoreable UTC-day window.

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

    items: list[tuple[pd.Timestamp, ScenarioSet, ScenarioSet, Any]] = []
    for block_start in range(first, len(starts), refit_days):
        block = range(block_start, min(block_start + refit_days, len(starts)))
        # Walk-forward: fit strictly before the block, predict through its end.
        forecaster = PriceForecaster(random_state=seed)
        forecaster.fit(prices[idx_norm < starts[block_start]])
        fc = forecaster.predict_interval(prices[idx_norm <= starts[block[-1]]])
        fc_days = pd.DatetimeIndex(fc.point.index).normalize()
        for i in block:
            day = starts[i]
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
            conf_set = generate_scenarios(conf_fc, c_res, n=n_scenarios, seed=seed + i)
            naive_set = generate_scenarios(naive_fc, n_res, n=n_scenarios, seed=seed + i)
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


# --------------------------------------------------------------------------- R2.5b
# Tail dispatch value: does the R2.2b/R2.2c scenario tail change the two-stage
# commitment's realized value versus the plain bootstrap? (spec R2.5b)


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


@dataclass(frozen=True)
class _MeanForecast:
    """A bare mean-day forecast: satisfies ``scenarios.PointForecast`` (only ``.point``
    is read), so the tail-value harness builds scenarios without the forecast group."""

    point: pd.Series


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
