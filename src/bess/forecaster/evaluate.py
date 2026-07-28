"""Forecast evaluation: walk-forward coverage, pinball loss, seasonal naive.

Spec: ``docs/specs/R2.1-forecaster.md`` § "Gates" (coverage),
``docs/specs/R2.1d-evaluation-honesty.md`` (fold placement + gate statistics), and
``docs/specs/R2.5-value-evaluation.md`` (pinball skill + the naive baseline);
math: ``formulation-r2.md`` §R2.1 / §R2.5. The honest test of a conformal
forecaster is **empirical coverage on data it did not calibrate on, under the R1.4
walk-forward discipline**: for each fold, fit on strictly-earlier data, predict a
later block, and check how often the realized price falls inside the interval.
No look-ahead: a fold never trains on data at or after its test block.

**Fold placement is a first-class object (R2.1d).** R2.1 took the last
``n_folds * test_days`` days as contiguous blocks, which on a 4-month window put
every fold inside a single fortnight, so "3 folds" was one evaluation reported
three times. ``rolling_origin_folds`` spreads folds across the whole span instead,
and takes a fixed-length rolling training window so folds are comparable to each
other rather than confounded with how much history happened to precede them. The
R2.1 placement is preserved exactly under ``spacing="contiguous"``.

**Coverage is reported with an interval (R2.1d).** Coverage indicators cluster
within a day (a bad day misses roughly 24 in a row), so the effective sample is
the *day* count, not the hour count. ``coverage_ci`` resamples whole days, which
is what makes the reported uncertainty honest and the gate decidable.

``pinball_loss``, ``seasonal_naive``, ``rolling_origin_folds`` and ``coverage_ci``
are pure numpy/pandas; the LightGBM-backed forecaster is imported lazily inside
the walk-forward functions so this module (and the R2.5 gates built on it) import
cleanly without the ``forecast`` group.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

#: Fold-placement defaults. R2.1's own values, kept so the historical coverage
#: number stays reproducible; the live gates pass R2.1d's wider settings.
DEFAULT_N_FOLDS = 3
DEFAULT_TEST_DAYS = 5


@dataclass(frozen=True)
class Fold:
    """One walk-forward fold: a training day range and a strictly later test block.

    ``train_end`` is **exclusive** (training uses days strictly before it) and
    ``test_end`` is **inclusive**, matching how the blocks are consumed below.
    """

    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


def rolling_origin_folds(
    days: pd.DatetimeIndex,
    *,
    n_folds: int,
    test_days: int,
    train_days: int | None = None,
    spacing: str = "even",
) -> list[Fold]:
    """Place ``n_folds`` non-overlapping test blocks of ``test_days`` days over ``days``.

    ``train_days=None`` gives the R2.1 **expanding** window (train from the first
    available day up to the block); an integer gives a **rolling** window of exactly
    that many days, so every fold is a like-for-like measurement.

    ``spacing="even"`` spreads the blocks across the whole span, inclusive of both
    ends, which is what makes pooled coverage a statement about the span rather than
    about its final fortnight. ``spacing="contiguous"`` reproduces R2.1 exactly: the
    blocks tile the *end* of the series.

    Raises ``ValueError`` if the span cannot host the request, rather than silently
    overlapping folds (which would pool the same test day into coverage twice) or
    shortening the first training window (which would make folds incomparable).
    """
    if spacing not in ("even", "contiguous"):
        raise ValueError(f"spacing must be 'even' or 'contiguous', got {spacing!r}")
    if n_folds < 1 or test_days < 1:
        raise ValueError("n_folds and test_days must be >= 1")
    if train_days is not None and train_days < 1:
        raise ValueError("train_days must be >= 1 when given")

    n = len(days)
    if spacing == "contiguous":
        # R2.1's formula verbatim, including its "series too short" condition.
        total_test = n_folds * test_days
        if n <= total_test + 1:
            raise ValueError("series too short for the requested walk-forward")
        starts = [n - total_test + i * test_days for i in range(n_folds)]
    else:
        # Earliest test day: a full training window must fit before it.
        lo = train_days if train_days is not None else 1
        hi = n - test_days  # latest start that still leaves a whole block
        if lo > hi:
            raise ValueError(
                f"span of {n} days cannot host a {test_days}-day block after a "
                f"{lo}-day training window"
            )
        if n_folds == 1:
            starts = [hi]
        else:
            # Non-overlapping requires the spread to cover (n_folds-1) whole blocks.
            if (hi - lo) < (n_folds - 1) * test_days:
                raise ValueError(
                    f"span of {n} days cannot host {n_folds} non-overlapping "
                    f"{test_days}-day blocks after a {lo}-day training window"
                )
            step = (hi - lo) / (n_folds - 1)
            starts = [lo + round(i * step) for i in range(n_folds)]

    folds = []
    for s in starts:
        train_start = days[s - train_days] if train_days is not None else days[0]
        folds.append(
            Fold(
                train_start=train_start,
                train_end=days[s],  # exclusive
                test_start=days[s],
                test_end=days[s + test_days - 1],  # inclusive
            )
        )
    return folds


def coverage_ci(
    covered_by_day: Sequence[np.ndarray],
    *,
    level: float = 0.95,
    n_boot: int = 2000,
    seed: int = 0,
) -> tuple[float, float]:
    """Day-block bootstrap interval for pooled coverage.

    ``covered_by_day`` holds one boolean array per evaluated day. Whole **days** are
    resampled with replacement, so intra-day dependence in the coverage indicator is
    preserved: pooling hours as if independent would understate the interval by
    roughly the square root of the day length, which is the error that made R2.1's
    fixed tolerance band narrower than the noise of the statistic it gated.

    Returns the ``level`` percentile interval. Deterministic for a fixed ``seed``.
    """
    if not 0.0 < level < 1.0:
        raise ValueError(f"level must be in (0, 1); got {level}")
    if len(covered_by_day) == 0:
        raise ValueError("no evaluated days to bootstrap")

    days_arr = [np.asarray(d, dtype=bool) for d in covered_by_day]
    hits = np.array([d.sum() for d in days_arr], dtype=float)
    sizes = np.array([d.size for d in days_arr], dtype=float)

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(days_arr), size=(n_boot, len(days_arr)))
    # Pooled coverage per resample: total hits over total observations, so days of
    # unequal length (a DST day) weight correctly.
    boot = hits[idx].sum(axis=1) / sizes[idx].sum(axis=1)

    tail = (1.0 - level) / 2.0
    lo, hi = np.quantile(boot, [tail, 1.0 - tail])
    return float(lo), float(hi)


def coverage_by_hour(hits: np.ndarray, hours: np.ndarray, *, n_hours: int = 24) -> np.ndarray:
    """Empirical coverage per hour-of-day bucket.

    The **conditional**-coverage axis (R2.1e). Conformal prediction guarantees only
    *marginal* coverage, so a forecaster can sit exactly on nominal overall while
    over-covering calm nights and under-covering volatile evening peaks. That split is
    invisible to a pooled number, and it is the property ADR-0014 chose CQR for:
    hour-adaptive interval width. Returns ``NaN`` for an hour with no
    observations rather than pretending to a rate it never measured.
    """
    hits = np.asarray(hits, dtype=bool)
    hours = np.asarray(hours, dtype=int)
    if hits.shape != hours.shape:
        raise ValueError("hits and hours must have the same shape")

    out = np.full(n_hours, np.nan)
    for h in range(n_hours):
        mask = hours == h
        if mask.any():
            out[h] = float(hits[mask].mean())
    return out


@dataclass(frozen=True)
class CoverageResult:
    """Pooled walk-forward coverage with its day-block interval and sharpness."""

    coverage: float
    ci_low: float
    ci_high: float
    mean_width: float
    n_test_days: int
    per_fold: tuple[float, ...]
    by_hour: tuple[float, ...] = ()
    max_hour_deviation: float = float("nan")


def _price_days(prices: pd.Series) -> pd.DatetimeIndex:
    """The distinct normalized UTC days a price series covers, ascending."""
    return pd.DatetimeIndex(sorted(pd.DatetimeIndex(prices.index).normalize().unique()))


def walk_forward_coverage(
    prices: pd.Series,
    *,
    confidence_level: float = 0.9,
    method: str = "cqr",
    n_folds: int = DEFAULT_N_FOLDS,
    test_days: int = DEFAULT_TEST_DAYS,
    train_days: int | None = None,
    spacing: str = "contiguous",
    fundamentals: pd.DataFrame | None = None,
    return_detail: bool = False,
    ci_level: float = 0.95,
    n_boot: int = 2000,
    seed: int = 0,
    **forecaster_params: Any,
) -> tuple[float, float] | CoverageResult:
    """Walk-forward empirical coverage of the conformal interval.

    For each fold from :func:`rolling_origin_folds`, a fresh forecaster is fit on the
    fold's training days and used to predict its test block (features for the block
    come from prior days, so no leakage). Coverage is pooled across all test points.

    Returns ``(coverage, mean_width)`` by default, or a :class:`CoverageResult` with
    the day-block bootstrap interval when ``return_detail`` is set. **The defaults
    are R2.1's** (three contiguous blocks at the end of the series, expanding
    training window), so existing callers are unchanged; R2.1d's gates pass
    ``spacing="even"`` with a ``train_days`` window.

    If ``fundamentals`` is given (R2.1c: a day-ahead ``load_da/wind_da/solar_da``
    frame), each fold's forecaster is fit and predicted with it (``make_features``
    reindexes it per fold, so passing the whole frame is safe). ``None`` is the R2.1
    behavior, byte-identical.
    """
    from bess.forecaster.forecast import PriceForecaster  # lazy: needs the forecast group

    folds = rolling_origin_folds(
        _price_days(prices),
        n_folds=n_folds,
        test_days=test_days,
        train_days=train_days,
        spacing=spacing,
    )
    norm = pd.DatetimeIndex(prices.index).normalize()

    covered_by_day: list[np.ndarray] = []
    per_fold: list[float] = []
    widths: list[float] = []
    hits_all: list[np.ndarray] = []
    hours_all: list[np.ndarray] = []
    for fold in folds:
        forecaster = PriceForecaster(
            confidence_level=confidence_level,
            method=method,
            use_fundamentals=fundamentals is not None,
            **forecaster_params,
        )
        train = prices[(norm >= fold.train_start) & (norm < fold.train_end)]
        hist_and_block = prices[(norm >= fold.train_start) & (norm <= fold.test_end)]
        forecaster.fit(train, fundamentals=fundamentals)
        forecast = forecaster.predict_interval(hist_and_block, fundamentals=fundamentals)

        f_norm = pd.DatetimeIndex(forecast.point.index).normalize()
        block_mask = (f_norm >= fold.test_start) & (f_norm <= fold.test_end)
        targets = forecast.point.index[block_mask]
        y_true = prices.loc[targets].to_numpy()
        lo = forecast.lower[block_mask].to_numpy()
        hi = forecast.upper[block_mask].to_numpy()
        hit = (y_true >= lo) & (y_true <= hi)

        # Grouped by day, so the bootstrap can resample whole days (R2.1d).
        for _, day_idx in pd.Series(hit, index=f_norm[block_mask]).groupby(level=0):
            covered_by_day.append(day_idx.to_numpy(dtype=bool))
        hits_all.append(hit)
        hours_all.append(pd.DatetimeIndex(targets).hour.to_numpy())
        per_fold.append(float(hit.mean()))
        widths.append(float((hi - lo).mean()))

    pooled_hits = np.concatenate(covered_by_day)
    coverage = float(pooled_hits.mean())
    mean_width = float(np.mean(widths))
    if not return_detail:
        return coverage, mean_width

    ci_low, ci_high = coverage_ci(covered_by_day, level=ci_level, n_boot=n_boot, seed=seed)
    hourly = coverage_by_hour(np.concatenate(hits_all), np.concatenate(hours_all))
    return CoverageResult(
        coverage=coverage,
        ci_low=ci_low,
        ci_high=ci_high,
        mean_width=mean_width,
        n_test_days=len(covered_by_day),
        per_fold=tuple(per_fold),
        by_hour=tuple(hourly),
        max_hour_deviation=float(np.nanmax(np.abs(hourly - confidence_level))),
    )


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
    n_folds: int = DEFAULT_N_FOLDS,
    test_days: int = DEFAULT_TEST_DAYS,
    train_days: int | None = None,
    spacing: str = "contiguous",
    lag_days: int = 7,
    fundamentals: pd.DataFrame | None = None,
    **forecaster_params: Any,
) -> PinballSkill:
    """Pinball loss at the interval edges under the R1.4 walk-forward, vs. naive.

    Same fold discipline as :func:`walk_forward_coverage`, sharing
    :func:`rolling_origin_folds` so the two axes are measured on identical blocks.
    The conformal forecaster's lower/upper bounds are scored as τ = α/2 and
    1 − α/2 quantile predictions; the seasonal-naive prediction is scored at the
    same τ as the degenerate baseline. Pass ``fundamentals`` (R2.1c) to score the
    fundamentals-augmented forecaster; ``None`` is the R2.1/R2.5 behavior.
    """
    from bess.forecaster.forecast import PriceForecaster  # lazy: needs the forecast group

    alpha = 1.0 - confidence_level
    tau_lo, tau_hi = alpha / 2.0, 1.0 - alpha / 2.0

    folds = rolling_origin_folds(
        _price_days(prices),
        n_folds=n_folds,
        test_days=test_days,
        train_days=train_days,
        spacing=spacing,
    )
    norm = pd.DatetimeIndex(prices.index).normalize()

    naive = seasonal_naive(prices, lag_days=lag_days)
    y_all: list[np.ndarray] = []
    lo_all: list[np.ndarray] = []
    hi_all: list[np.ndarray] = []
    nv_all: list[np.ndarray] = []
    for fold in folds:
        forecaster = PriceForecaster(
            confidence_level=confidence_level,
            method=method,
            use_fundamentals=fundamentals is not None,
            **forecaster_params,
        )
        train = prices[(norm >= fold.train_start) & (norm < fold.train_end)]
        hist_and_block = prices[(norm >= fold.train_start) & (norm <= fold.test_end)]
        forecaster.fit(train, fundamentals=fundamentals)
        forecast = forecaster.predict_interval(hist_and_block, fundamentals=fundamentals)

        f_norm = pd.DatetimeIndex(forecast.point.index).normalize()
        block_mask = (f_norm >= fold.test_start) & (f_norm <= fold.test_end)
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
