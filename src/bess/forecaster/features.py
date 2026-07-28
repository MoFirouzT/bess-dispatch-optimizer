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

import numpy as np
import pandas as pd

from bess.data.fixtures import PRICE_COL

DEFAULT_LAGS: tuple[int, ...] = (24, 48, 72, 168)  # hours; all ≥ 24 h ⇒ prior-day only


def _dt_hours(index: pd.DatetimeIndex) -> float:
    """Resolution of a regular series in hours (24 → hourly lag counts)."""
    return (index[1] - index[0]).total_seconds() / 3600.0


#: Fundamentals feature columns (R2.1c). Grid-side day-ahead forecasts in MW,
#: aligned *contemporaneously* to the target (not lagged); see ``fundamentals`` below.
FUNDAMENTAL_COLS: tuple[str, ...] = ("load_da", "wind_da", "solar_da")

#: R2.1e baseline defaults. The window ends ``gap_h`` hours before the target, so a
#: baseline for ``t`` is known at gate closure for ``t`` (same argument as the lags).
DEFAULT_BASELINE_WINDOW_H = 168
DEFAULT_BASELINE_GAP_H = 24
#: Floor on the scale estimate, in EUR/MWh. Real NL history contains runs of
#: identical prices (R2.1d measured a 5-hour run at exactly 64.00 and 0.00 runs up to
#: 8 hours), so an unfloored standard deviation really does hit zero on real input and
#: the inverse transform would divide by it.
DEFAULT_SCALE_FLOOR = 1.0


def rolling_baseline(
    prices: pd.Series,
    *,
    window_h: int = DEFAULT_BASELINE_WINDOW_H,
    gap_h: int = DEFAULT_BASELINE_GAP_H,
    scale_floor: float = DEFAULT_SCALE_FLOOR,
) -> pd.DataFrame:
    """Trailing level and scale per target, from prices at or before ``t - gap_h``.

    Returns a frame with ``level`` (mean) and ``scale`` (population standard
    deviation, floored) on ``prices``' index; the warm-up rows are ``NaN``. This is
    the R2.1e de-levelling pair: the target is standardized as
    ``(price - level) / scale`` and inverted with :func:`invert_standardized`.

    **Leakage-safe by construction.** The window spans the ``window_h`` hours ending
    **at** ``t - gap_h`` inclusive, so it reaches no later than the price ``gap_h``
    hours before the target. At the default ``gap_h=24`` that is the same bound the
    ``>= 24 h`` lags already use: for a target on day ``D`` it reads nothing newer
    than the same hour on ``D-1``, which the day-ahead auction has already published
    at gate closure. That is what makes the inverse transform a *known* constant at
    prediction time, which is the whole basis of the inherited coverage guarantee.
    """
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise ValueError("prices must have a DatetimeIndex")
    if window_h < 1 or gap_h < 1:
        raise ValueError("window_h and gap_h must be >= 1")
    if scale_floor <= 0.0:
        raise ValueError("scale_floor must be > 0 so the inverse transform is finite")

    dt_h = _dt_hours(prices.index) if len(prices.index) >= 2 else 1.0
    gap = round(gap_h / dt_h)
    window = round(window_h / dt_h)

    past = prices.shift(gap)  # everything at or after t - gap_h is now out of reach
    level = past.rolling(window, min_periods=window).mean()
    # Population (ddof=0) standard deviation: the oracle's "known std" is the
    # population one, and with a 168-point window the ddof choice is immaterial
    # numerically but must be pinned so the golden stays exact.
    scale = past.rolling(window, min_periods=window).std(ddof=0).clip(lower=scale_floor)
    return pd.DataFrame({"level": level, "scale": scale}, index=prices.index)


def invert_standardized(z: pd.Series, baseline: pd.DataFrame) -> pd.Series:
    """Map a standardized quantity back to price space: ``level + scale * z``.

    ``baseline`` comes from :func:`rolling_baseline`. The map is affine with a
    strictly positive slope, so it is order preserving: applying it to a lower bound,
    a point forecast and an upper bound keeps them ordered, and an interval covering
    the standardized target covers the price exactly as often. That equality is what
    lets R2.1e inherit R2.1's conformal coverage guarantee rather than re-derive it.
    """
    lvl = baseline["level"].reindex(z.index)
    scl = baseline["scale"].reindex(z.index)
    out: pd.Series = lvl + scl * z
    out.name = z.name
    return out


def make_features(
    prices: pd.Series,
    *,
    lags: tuple[int, ...] = DEFAULT_LAGS,
    calendar: bool = True,
    country: str | None = None,
    fundamentals: pd.DataFrame | None = None,
    normalize: pd.DataFrame | None = None,
    season_encoding: str = "month",
    rolling_stats: bool = False,
) -> pd.DataFrame:
    """Build the leakage-safe feature matrix for forecasting ``prices``.

    Returns a frame indexed by the target timestamps for which *every* lag is
    available (the first ``max(lags)`` are dropped). Columns: one ``lag_<h>`` per
    lag (the price ``h`` hours earlier) plus, if ``calendar``, cyclical/categorical
    calendar fields. If ``country`` is given and ``holidays`` is installed, adds an
    ``is_holiday`` flag. Every column at row ``t`` depends only on information from
    strictly before ``t`` (prior-day prices, or the calendar of ``t`` itself).

    **Fundamentals (R2.1c, opt-in).** If ``fundamentals`` is given, its columns
    (a subset of ``load_da``/``wind_da``/``solar_da``, day-ahead forecasts in MW on
    the same UTC grid as ``prices``) are added **aligned to the target ``t`` itself**,
    not shifted into the past. This is leakage-safe *because these are published
    forecasts for day ``D``, not outcomes* (see docs/decisions/forecast-feature-alignment.md), so a
    value for ``t`` exists
    before ``t`` occurs — never pass realized actuals. docs/decisions/forecast-feature-alignment.md
    scopes that safety:
    load is published before day-ahead gate closure, wind/solar only after it, so a
    decision taken *at* gate closure is not covered.
    When all three components are present, a ``residual_load = load_da − wind_da −
    solar_da`` column is added (the merit-order driver). ``fundamentals=None`` is
    byte-identical to the R2.1 feature matrix (the opt-in identity).

    **Normalization (R2.1e, opt-in).** Pass a :func:`rolling_baseline` frame as
    ``normalize`` and every lag column is expressed in standardized units,
    ``(price[t-h] - level_t) / scale_t``, so the tree splits on a stationary quantity
    instead of a price level that drifts by roughly 3x across the evaluation span.
    Calendar features are unaffected and fundamentals stay in MW (bounded physical
    quantities without the price's level drift). ``normalize=None`` is byte-identical
    to R2.1d. ``season_encoding="cyclical"`` swaps the plain ``month`` number for
    day-of-year sine and cosine; ``rolling_stats=True`` adds the trailing level and
    scale, and a prior-day mean, as features in their own right.
    """
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise ValueError("prices must have a DatetimeIndex")
    if season_encoding not in ("month", "cyclical"):
        raise ValueError(f"season_encoding must be 'month' or 'cyclical', got {season_encoding!r}")
    dt_h = _dt_hours(prices.index) if len(prices.index) >= 2 else 1.0

    feats: dict[str, pd.Series] = {}
    for lag_h in lags:
        periods = round(lag_h / dt_h)
        lagged = prices.shift(periods)  # shift into the past ⇒ π[t−lag]
        if normalize is not None:
            lagged = (lagged - normalize["level"]) / normalize["scale"]
        feats[f"lag_{lag_h}"] = lagged

    idx = prices.index
    if calendar:
        feats["hour"] = pd.Series(idx.hour, index=idx, dtype="float64")
        feats["dayofweek"] = pd.Series(idx.dayofweek, index=idx, dtype="float64")
        # Season as a plain month number. A cyclical (sin/cos day-of-year) encoding was
        # tried and **reverted** (2026-07-26): it is the right encoding only once
        # training spans a full year, and it is worse than this on the 4-month windows
        # actually in use. Two measured reasons. (1) It does not buy the range safety
        # it appears to: the pair is bounded in [-1, 1] globally, but a Feb-Jun fit
        # only ever sees doy_sin [0.503, 1.000] / doy_cos [-0.864, 0.861], and mid
        # December sits outside *both* (-0.276, +0.961), so trees extrapolate exactly
        # as they do here. (2) Inside such a window it is strictly the weaker signal:
        # doy_sin turns over at the summer solstice (doy 92), so one value maps to two
        # dates, while `month` stays monotone and unambiguous. Empirically it left
        # out-of-season coverage unchanged and pushed the in-season split gate to
        # over-cover (0.920 → 0.961, outside [0.85, 0.95]). See docs/STATE.md.
        #
        # **R2.1e re-enables it behind `season_encoding="cyclical"`, and the revert
        # above is still the right call for its own context.** What changed is the
        # precondition, not the argument: R2.1d moved the harness to a fixed 365-day
        # rolling training window, so every fit now spans a full year and the
        # out-of-range objection (1) no longer applies. Objection (2) also lapses,
        # since a full-year window sees both sides of the solstice. On a short window
        # `month` remains the better feature, which is why this stays the default.
        if season_encoding == "cyclical":
            doy = pd.Series(idx.dayofyear, index=idx, dtype="float64")
            angle = 2.0 * np.pi * doy / 365.25
            feats["doy_sin"] = pd.Series(np.sin(angle), index=idx, dtype="float64")
            feats["doy_cos"] = pd.Series(np.cos(angle), index=idx, dtype="float64")
        else:
            feats["month"] = pd.Series(idx.month, index=idx, dtype="float64")
        feats["is_weekend"] = pd.Series((idx.dayofweek >= 5).astype("float64"), index=idx)
        if country is not None:
            holiday_flag = _holiday_flag(idx, country)
            if holiday_flag is not None:
                feats["is_holiday"] = holiday_flag

    if rolling_stats:
        # The trailing statistics R2.1's scope section promised and never delivered
        # (corrected there 2026-07-28). Exposed as features, not only as the transform:
        # the level and scale carry regime information the standardized lags no longer
        # do, precisely because they were divided out.
        base = normalize if normalize is not None else rolling_baseline(prices)
        feats["trailing_level"] = base["level"]
        feats["trailing_scale"] = base["scale"]
        prior_day = prices.shift(round(24 / dt_h)).rolling(round(24 / dt_h)).mean()
        if normalize is not None:
            prior_day = (prior_day - base["level"]) / base["scale"]
        feats["prior_day_mean"] = prior_day

    if fundamentals is not None:
        fund = fundamentals.reindex(idx)  # contemporaneous, label-aligned to the targets
        if all(c in fund.columns for c in FUNDAMENTAL_COLS):
            feats["residual_load"] = fund["load_da"] - fund["wind_da"] - fund["solar_da"]
        for col in FUNDAMENTAL_COLS:
            if col in fund.columns:
                feats[col] = fund[col].astype("float64")

    frame = pd.DataFrame(feats, index=idx)
    return frame.dropna()  # drop the warm-up rows where a lag (or fundamental) is unavailable


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
