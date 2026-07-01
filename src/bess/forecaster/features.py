"""Leakage-safe feature construction for the day-ahead price forecaster (R2.1).

Spec: ``docs/specs/R2.1-forecaster.md``. Every feature for a target timestamp ``t``
is derived **strictly from prices of prior days**, which is exactly what is known at
gate closure: day-ahead auctions publish a full day's curve at once, so at the
D-gate-closure all prices for days ``≤ D-1`` are available. Lags are therefore
``≥ 24 h`` and computed by shifting the series into the past — a feature at ``t``
never reads ``π_t`` or any same-day/future price (the no-leakage invariant, tested).

Pure pandas: this module needs neither LightGBM nor MAPIE, so the leakage/feature
gates run without the ``forecast`` dependency group. Calendar features are derived
from the index alone; an optional public-holiday flag is added only when a country
is given and the ``holidays`` package is installed.

``forecaster`` may import ``bess.data`` (a leaf) but nothing above it (import-linter).
"""

from __future__ import annotations

import pandas as pd

from bess.data.fixtures import PRICE_COL

DEFAULT_LAGS: tuple[int, ...] = (24, 48, 72, 168)  # hours; all ≥ 24 h ⇒ prior-day only


def _dt_hours(index: pd.DatetimeIndex) -> float:
    """Resolution of a regular series in hours (24 → hourly lag counts)."""
    return (index[1] - index[0]).total_seconds() / 3600.0


def make_features(
    prices: pd.Series,
    *,
    lags: tuple[int, ...] = DEFAULT_LAGS,
    calendar: bool = True,
    country: str | None = None,
) -> pd.DataFrame:
    """Build the leakage-safe feature matrix for forecasting ``prices``.

    Returns a frame indexed by the target timestamps for which *every* lag is
    available (the first ``max(lags)`` are dropped). Columns: one ``lag_<h>`` per
    lag (the price ``h`` hours earlier) plus, if ``calendar``, cyclical/categorical
    calendar fields. If ``country`` is given and ``holidays`` is installed, adds an
    ``is_holiday`` flag. Every column at row ``t`` depends only on information from
    strictly before ``t`` (prior-day prices, or the calendar of ``t`` itself).
    """
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise ValueError("prices must have a DatetimeIndex")
    dt_h = _dt_hours(prices.index) if len(prices.index) >= 2 else 1.0

    feats: dict[str, pd.Series] = {}
    for lag_h in lags:
        periods = round(lag_h / dt_h)
        feats[f"lag_{lag_h}"] = prices.shift(periods)  # shift into the past ⇒ π[t−lag]

    idx = prices.index
    if calendar:
        feats["hour"] = pd.Series(idx.hour, index=idx, dtype="float64")
        feats["dayofweek"] = pd.Series(idx.dayofweek, index=idx, dtype="float64")
        feats["month"] = pd.Series(idx.month, index=idx, dtype="float64")
        feats["is_weekend"] = pd.Series((idx.dayofweek >= 5).astype("float64"), index=idx)
        if country is not None:
            holiday_flag = _holiday_flag(idx, country)
            if holiday_flag is not None:
                feats["is_holiday"] = holiday_flag

    frame = pd.DataFrame(feats, index=idx)
    return frame.dropna()  # drop the warm-up rows where a lag is unavailable


def align_target(prices: pd.Series, features: pd.DataFrame) -> pd.Series:
    """The target series aligned to a feature frame's index (the price *at* ``t``)."""
    y = prices.loc[features.index].astype(float)
    y.name = PRICE_COL
    return y


def _holiday_flag(index: pd.DatetimeIndex, country: str) -> pd.Series | None:
    """A 0/1 public-holiday flag for ``country``; ``None`` if ``holidays`` is absent."""
    try:
        import holidays as holidays_lib
    except ImportError:
        return None
    years = range(index.year.min(), index.year.max() + 1)
    cal = holidays_lib.country_holidays(country, years=list(years))
    flags = [1.0 if d.date() in cal else 0.0 for d in index]
    return pd.Series(flags, index=index, dtype="float64")
