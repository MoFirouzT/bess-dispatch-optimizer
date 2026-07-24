"""Probabilistic day-ahead price forecaster: LightGBM + conformal intervals (R2.1).

Spec: ``docs/specs/R2.1-forecaster.md``; theory summary: ``formulation.md`` §R2.1.
Wraps a gradient-boosted base learner in a MAPIE conformal calibrator so the output
is a **calibrated interval**, not a point. Two methods:

- ``"cqr"`` (default, [ADR-0014](../../docs/decisions/0014-cqr-over-split-conformal.md)) —
  conformalized quantile regression over three prefit LightGBM quantile models
  ``[lower, upper, median]``; interval width adapts to the (heteroscedastic) price.
- ``"split"`` — split conformal over one point model; constant-width baseline.

Both give a distribution-free marginal-coverage guarantee under exchangeability,
checked empirically by the walk-forward coverage gate (``evaluate.py``).

This module imports LightGBM and MAPIE (the ``forecast`` dependency group); the
leakage-safe feature construction lives in ``features.py`` and needs neither.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from mapie.regression import ConformalizedQuantileRegressor, SplitConformalRegressor

from bess.forecaster.features import DEFAULT_LAGS, align_target, make_features

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, eq=False)
class IntervalForecast:
    """A calibrated interval forecast, indexed by target timestamp."""

    point: pd.Series
    lower: pd.Series
    upper: pd.Series
    confidence_level: float

    @property
    def width(self) -> pd.Series:
        """Interval width per target (``upper − lower``)."""
        return (self.upper - self.lower).rename("width")


class PriceForecaster:
    """Fit LightGBM quantile/point learners and conformalize them into price intervals.

    ``fit`` splits its input temporally into a proper-training block and a strictly
    later calibration block (never a random split — leakage discipline), fits the
    base learner(s) on the former, and conformalizes on the latter. ``recalibrate``
    refreshes only the conformal step (the rolling 7-day recalibration), leaving the
    base models untouched. All model calls use single-threaded deterministic
    LightGBM so a fixed seed reproduces the intervals bit-for-bit.
    """

    def __init__(
        self,
        *,
        confidence_level: float = 0.9,
        method: str = "cqr",
        lags: tuple[int, ...] = DEFAULT_LAGS,
        calendar: bool = True,
        country: str | None = None,
        calib_fraction: float = 0.3,
        n_estimators: int = 200,
        random_state: int = 0,
        use_fundamentals: bool = False,
        **lgb_params: object,
    ) -> None:
        if method not in ("cqr", "split"):
            raise ValueError(f"method must be 'cqr' or 'split', got {method!r}")
        if not 0.0 < confidence_level < 1.0:
            raise ValueError("confidence_level must be in (0, 1)")
        self.confidence_level = confidence_level
        self.method = method
        self.lags = lags
        self.calendar = calendar
        self.country = country
        self.use_fundamentals = use_fundamentals
        self.calib_fraction = calib_fraction
        # Deterministic, single-threaded LightGBM so intervals are reproducible.
        self._lgb = dict(
            n_estimators=n_estimators,
            random_state=random_state,
            n_jobs=1,
            deterministic=True,
            verbose=-1,
            **lgb_params,
        )
        self._mapie: ConformalizedQuantileRegressor | SplitConformalRegressor | None = None

    def _lgbm(self, **extra: object) -> LGBMRegressor:
        return LGBMRegressor(**{**self._lgb, **extra})

    def _features(self, prices: pd.Series, fundamentals: pd.DataFrame | None) -> pd.DataFrame:
        """Build the feature matrix, honoring ``use_fundamentals`` with graceful fallback.

        When ``use_fundamentals`` is set but no fundamentals frame is supplied, fall
        back to the R2.1 price+calendar features and log a warning (R1.5/R1.4c
        reliability posture: a degraded-but-valid forecast beats none). When it is
        off, ``fundamentals`` is ignored so the output is byte-identical to R2.1.
        """
        fund = None
        if self.use_fundamentals:
            if fundamentals is None:
                _logger.warning(
                    "use_fundamentals=True but no fundamentals supplied; "
                    "falling back to price+calendar features"
                )
            else:
                fund = fundamentals
        return make_features(
            prices,
            lags=self.lags,
            calendar=self.calendar,
            country=self.country,
            fundamentals=fund,
        )

    def _matrix(
        self, prices: pd.Series, fundamentals: pd.DataFrame | None = None
    ) -> tuple[np.ndarray, pd.DatetimeIndex]:
        feats = self._features(prices, fundamentals)
        return feats.to_numpy(), pd.DatetimeIndex(feats.index)

    def fit(
        self, prices: pd.Series, *, fundamentals: pd.DataFrame | None = None
    ) -> PriceForecaster:
        feats = self._features(prices, fundamentals)
        y = align_target(prices, feats)
        x = feats.to_numpy()
        yv = y.to_numpy()
        cut = int(len(x) * (1.0 - self.calib_fraction))
        if cut < 1 or cut >= len(x):
            raise ValueError("not enough data to form train + calibration splits")
        x_tr, y_tr, x_ca, y_ca = x[:cut], yv[:cut], x[cut:], yv[cut:]

        alpha = 1.0 - self.confidence_level
        if self.method == "cqr":
            lo = self._lgbm(objective="quantile", alpha=alpha / 2).fit(x_tr, y_tr)
            hi = self._lgbm(objective="quantile", alpha=1.0 - alpha / 2).fit(x_tr, y_tr)
            med = self._lgbm(objective="quantile", alpha=0.5).fit(x_tr, y_tr)
            mapie = ConformalizedQuantileRegressor(
                [lo, hi, med], confidence_level=self.confidence_level, prefit=True
            )
        else:  # split
            est = self._lgbm().fit(x_tr, y_tr)
            mapie = SplitConformalRegressor(
                est, confidence_level=self.confidence_level, prefit=True
            )
        mapie.conformalize(x_ca, y_ca)
        self._mapie = mapie
        return self

    def predict_interval(
        self, prices: pd.Series, *, fundamentals: pd.DataFrame | None = None
    ) -> IntervalForecast:
        if self._mapie is None:
            raise RuntimeError("call fit() before predict_interval()")
        x, idx = self._matrix(prices, fundamentals)
        pred, interval = self._mapie.predict_interval(x)
        return IntervalForecast(
            point=pd.Series(np.asarray(pred).ravel(), index=idx, name="point"),
            lower=pd.Series(interval[:, 0, 0], index=idx, name="lower"),
            upper=pd.Series(interval[:, 1, 0], index=idx, name="upper"),
            confidence_level=self.confidence_level,
        )

    def recalibrate(
        self, recent_prices: pd.Series, *, fundamentals: pd.DataFrame | None = None
    ) -> PriceForecaster:
        """Refresh the conformal calibration on a recent window; base models unchanged."""
        if self._mapie is None:
            raise RuntimeError("call fit() before recalibrate()")
        feats = self._features(recent_prices, fundamentals)
        y = align_target(recent_prices, feats)
        self._mapie.conformalize(feats.to_numpy(), y.to_numpy())
        return self
