"""Forecast evaluation: walk-forward coverage, pinball loss, seasonal naive.

Spec: ``docs/specs/R2.1-forecaster.md`` § "Gates" (coverage) and
``docs/specs/R2.5-value-evaluation.md`` (pinball skill + the naive baseline);
math: ``formulation.md`` §R2.1 / §R2.5. The honest test of a conformal
forecaster is **empirical coverage on data it did not calibrate on, under the R1.4
walk-forward discipline**: for each fold, fit on all strictly-earlier data, predict
a later block, and check how often the realized price falls inside the interval.
Aggregated coverage should land in ``confidence_level ± tolerance`` (the coverage
gate). No look-ahead: a fold never trains on data at or after its test block.

``pinball_loss`` and ``seasonal_naive`` are pure numpy/pandas; the LightGBM-backed
forecaster is imported lazily inside ``walk_forward_coverage`` so this module (and
the R2.5 gates built on it) import cleanly without the ``forecast`` group.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


def walk_forward_coverage(
    prices: pd.Series,
    *,
    confidence_level: float = 0.9,
    method: str = "cqr",
    n_folds: int = 3,
    test_days: int = 5,
    fundamentals: pd.DataFrame | None = None,
    **forecaster_params: Any,
) -> tuple[float, float]:
    """Return ``(empirical_coverage, mean_interval_width)`` over a walk-forward.

    The last ``n_folds * test_days`` days are split into ``n_folds`` consecutive test
    blocks. For each block, a fresh forecaster is fit on all days strictly before the
    block and used to predict it (features for the block come from prior days, so no
    leakage). Coverage is pooled across all test points.

    If ``fundamentals`` is given (R2.1c: a day-ahead ``load_da/wind_da/solar_da``
    frame), each fold's forecaster is fit and predicted with it (``make_features``
    reindexes it per fold, so passing the whole frame is safe). ``None`` is the R2.1
    behavior, byte-identical.
    """
    from bess.forecaster.forecast import PriceForecaster  # lazy: needs the forecast group

    days = np.array(sorted(pd.DatetimeIndex(prices.index).normalize().unique()))
    total_test = n_folds * test_days
    if len(days) <= total_test + 1:
        raise ValueError("series too short for the requested walk-forward")

    covered = 0
    count = 0
    widths: list[float] = []
    for fold in range(n_folds):
        start = len(days) - total_test + fold * test_days
        test_days_block = days[start : start + test_days]
        block_start, block_end = test_days_block[0], test_days_block[-1]

        norm = pd.DatetimeIndex(prices.index).normalize()
        train = prices[norm < block_start]
        hist_and_block = prices[norm <= block_end]

        forecaster = PriceForecaster(
            confidence_level=confidence_level,
            method=method,
            use_fundamentals=fundamentals is not None,
            **forecaster_params,
        )
        forecaster.fit(train, fundamentals=fundamentals)
        forecast = forecaster.predict_interval(hist_and_block, fundamentals=fundamentals)

        f_norm = pd.DatetimeIndex(forecast.point.index).normalize()
        block_mask = (f_norm >= block_start) & (f_norm <= block_end)
        targets = forecast.point.index[block_mask]
        y_true = prices.loc[targets].to_numpy()
        lo = forecast.lower[block_mask].to_numpy()
        hi = forecast.upper[block_mask].to_numpy()

        covered += int(((y_true >= lo) & (y_true <= hi)).sum())
        count += len(targets)
        widths.append(float((hi - lo).mean()))

    return covered / count, float(np.mean(widths))


def pinball_loss(y_true: Any, y_pred: Any, *, tau: float) -> float:
    """Mean quantile (pinball) loss ``max{τ(y−q̂), (τ−1)(y−q̂)}`` (formulation §R2.5).

    Scores a τ-quantile prediction: under-predicting a high quantile costs τ per
    unit, over-predicting only 1−τ. At τ=0.5 it equals MAE/2. Non-negative, zero
    iff every prediction is exact.
    """
    if not 0.0 < tau < 1.0:
        raise ValueError(f"tau must be in (0, 1); got {tau}")
    d = np.asarray(y_true, dtype=float) - np.asarray(y_pred, dtype=float)
    return float(np.mean(np.maximum(tau * d, (tau - 1.0) * d)))


def seasonal_naive(prices: pd.Series, *, lag_days: int = 7) -> pd.Series:
    """Calendar-lagged naive prediction: the actual price ``lag_days`` earlier.

    The R2.5 skill baseline: predicts each timestamp from the same hour
    ``lag_days`` (default one week) prior, falling back to the previous day
    where the seasonal lag has no history yet, and dropping timestamps with
    neither. Calendar-shifted (robust to gaps), unlike the position-shifted
    ``drift.seasonal_naive_forecast`` the drift monitor uses on its rolling
    windows.
    """
    if lag_days < 1:
        raise ValueError(f"lag_days must be >= 1; got {lag_days}")
    idx = pd.DatetimeIndex(prices.index)
    week = prices.set_axis(idx + pd.Timedelta(days=lag_days)).reindex(idx)
    day = prices.set_axis(idx + pd.Timedelta(days=1)).reindex(idx)
    return week.fillna(day).dropna().rename("naive")


@dataclass(frozen=True)
class PinballSkill:
    """Walk-forward pinball losses at the interval edges, conformal vs. naive.

    ``skill_* = conformal / naive`` at the same τ; below 1 means the forecaster's
    quantile beats the seasonal-naive point used as a degenerate quantile. The
    accuracy axis next to the R2.1 coverage gate (formulation §R2.5).
    """

    tau_lower: float
    tau_upper: float
    conformal_lower: float
    conformal_upper: float
    naive_lower: float
    naive_upper: float
    skill_lower: float
    skill_upper: float


def walk_forward_pinball_skill(
    prices: pd.Series,
    *,
    confidence_level: float = 0.9,
    method: str = "cqr",
    n_folds: int = 3,
    test_days: int = 5,
    lag_days: int = 7,
    fundamentals: pd.DataFrame | None = None,
    **forecaster_params: Any,
) -> PinballSkill:
    """Pinball loss at the interval edges under the R1.4 walk-forward, vs. naive.

    Same fold discipline as :func:`walk_forward_coverage` (fit strictly before
    each test block, pool across blocks). The conformal forecaster's lower/upper
    bounds are scored as τ = α/2 and 1 − α/2 quantile predictions; the seasonal-
    naive prediction is scored at the same τ as the degenerate baseline. Pass
    ``fundamentals`` (R2.1c) to score the fundamentals-augmented forecaster; ``None``
    is the R2.1/R2.5 behavior.
    """
    from bess.forecaster.forecast import PriceForecaster  # lazy: needs the forecast group

    alpha = 1.0 - confidence_level
    tau_lo, tau_hi = alpha / 2.0, 1.0 - alpha / 2.0

    days = np.array(sorted(pd.DatetimeIndex(prices.index).normalize().unique()))
    total_test = n_folds * test_days
    if len(days) <= total_test + 1:
        raise ValueError("series too short for the requested walk-forward")

    naive = seasonal_naive(prices, lag_days=lag_days)
    y_all: list[np.ndarray] = []
    lo_all: list[np.ndarray] = []
    hi_all: list[np.ndarray] = []
    nv_all: list[np.ndarray] = []
    for fold in range(n_folds):
        start = len(days) - total_test + fold * test_days
        block_start, block_end = days[start], days[start + test_days - 1]

        norm = pd.DatetimeIndex(prices.index).normalize()
        forecaster = PriceForecaster(
            confidence_level=confidence_level,
            method=method,
            use_fundamentals=fundamentals is not None,
            **forecaster_params,
        )
        forecaster.fit(prices[norm < block_start], fundamentals=fundamentals)
        forecast = forecaster.predict_interval(prices[norm <= block_end], fundamentals=fundamentals)

        f_norm = pd.DatetimeIndex(forecast.point.index).normalize()
        block_mask = (f_norm >= block_start) & (f_norm <= block_end)
        targets = forecast.point.index[block_mask]
        y_all.append(prices.loc[targets].to_numpy(dtype=float))
        lo_all.append(forecast.lower[block_mask].to_numpy(dtype=float))
        hi_all.append(forecast.upper[block_mask].to_numpy(dtype=float))
        nv_all.append(naive.loc[targets].to_numpy(dtype=float))

    y = np.concatenate(y_all)
    nv = np.concatenate(nv_all)
    c_lo = pinball_loss(y, np.concatenate(lo_all), tau=tau_lo)
    c_hi = pinball_loss(y, np.concatenate(hi_all), tau=tau_hi)
    n_lo = pinball_loss(y, nv, tau=tau_lo)
    n_hi = pinball_loss(y, nv, tau=tau_hi)
    return PinballSkill(
        tau_lower=tau_lo,
        tau_upper=tau_hi,
        conformal_lower=c_lo,
        conformal_upper=c_hi,
        naive_lower=n_lo,
        naive_upper=n_hi,
        skill_lower=c_lo / n_lo,
        skill_upper=c_hi / n_hi,
    )
