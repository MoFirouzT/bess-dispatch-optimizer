"""Probabilistic day-ahead price forecaster: LightGBM + conformal intervals (R2.1).

Spec: ``docs/specs/R2.1-forecaster.md``; theory summary: ``formulation-uncertainty.md`` §R2.1.
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

from bess.forecaster.features import (
    DEFAULT_LAGS,
    align_target,
    invert_standardized,
    make_features,
    rolling_baseline,
)

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, eq=False)
class IntervalForecast:
    """A calibrated interval forecast, indexed by target timestamp."""

    point: pd.Series
    lower: pd.Series
    upper: pd.Series
    confidence_level: float
    #: How many targets had their point forecast clipped back into the interval
    #: (quantile crossing; see ``PriceForecaster.predict_interval``). Normally a
    #: handful out of thousands. A large value means the median model disagrees
    #: with its own quantile models, so the clip is hiding a bad fit rather than
    #: tidying an edge case, and it is surfaced here rather than left silent.
    n_point_clipped: int = 0

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
        normalize_target: bool = False,
        season_encoding: str = "month",
        rolling_stats: bool = False,
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
        # R2.1e: fit on a de-levelled, de-scaled target and invert on predict. The
        # inverse is a known, strictly increasing affine map (level + scale*z) with
        # level/scale fixed at prediction time, so R2.1's conformal coverage
        # guarantee is inherited unchanged; see docs/specs/R2.1e-target-normalization.md.
        self.normalize_target = normalize_target
        self.season_encoding = season_encoding
        self.rolling_stats = rolling_stats
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
        # The fitted base learner(s), kept so ``recalibrate`` can rewrap them.
        self._base: list[LGBMRegressor] | LGBMRegressor | None = None

    def _lgbm(self, **extra: object) -> LGBMRegressor:
        return LGBMRegressor(**{**self._lgb, **extra})

    def _conformalizer(
        self, base: list[LGBMRegressor] | LGBMRegressor
    ) -> ConformalizedQuantileRegressor | SplitConformalRegressor:
        """Wrap already-fitted base learner(s) in a fresh, un-conformalized estimator.

        A *fresh* wrapper each time is the point: MAPIE allows ``conformalize`` once
        per estimator and raises on a second call, so recalibration cannot reuse the
        object built by ``fit``. Both wrappers take ``prefit=True``, so rewrapping
        re-runs no training; only the conformal quantile is recomputed.
        """
        if self.method == "cqr":
            return ConformalizedQuantileRegressor(
                base, confidence_level=self.confidence_level, prefit=True
            )
        return SplitConformalRegressor(base, confidence_level=self.confidence_level, prefit=True)

    def _baseline(self, prices: pd.Series) -> pd.DataFrame | None:
        """The R2.1e level/scale pair for these prices, or ``None`` when off."""
        return rolling_baseline(prices) if self.normalize_target else None

    def _features(
        self,
        prices: pd.Series,
        fundamentals: pd.DataFrame | None,
        baseline: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
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
            normalize=baseline,
            season_encoding=self.season_encoding,
            rolling_stats=self.rolling_stats,
        )

    def _matrix(
        self, prices: pd.Series, fundamentals: pd.DataFrame | None = None
    ) -> tuple[np.ndarray, pd.DatetimeIndex]:
        feats = self._features(prices, fundamentals, self._baseline(prices))
        return feats.to_numpy(), pd.DatetimeIndex(feats.index)

    def _standardize(self, y: pd.Series, baseline: pd.DataFrame | None) -> pd.Series:
        """The training target: raw price, or ``(price - level) / scale`` (R2.1e)."""
        if baseline is None:
            return y
        return (y - baseline["level"].reindex(y.index)) / baseline["scale"].reindex(y.index)

    def fit(
        self, prices: pd.Series, *, fundamentals: pd.DataFrame | None = None
    ) -> PriceForecaster:
        baseline = self._baseline(prices)
        feats = self._features(prices, fundamentals, baseline)
        y = self._standardize(align_target(prices, feats), baseline)
        x = feats.to_numpy()
        yv = y.to_numpy()
        cut = int(len(x) * (1.0 - self.calib_fraction))
        if cut < 1 or cut >= len(x):
            raise ValueError("not enough data to form train + calibration splits")
        x_tr, y_tr, x_ca, y_ca = x[:cut], yv[:cut], x[cut:], yv[cut:]

        alpha = 1.0 - self.confidence_level
        base: list[LGBMRegressor] | LGBMRegressor
        if self.method == "cqr":
            base = [
                self._lgbm(objective="quantile", alpha=alpha / 2).fit(x_tr, y_tr),
                self._lgbm(objective="quantile", alpha=1.0 - alpha / 2).fit(x_tr, y_tr),
                self._lgbm(objective="quantile", alpha=0.5).fit(x_tr, y_tr),
            ]
        else:  # split
            base = self._lgbm().fit(x_tr, y_tr)

        mapie = self._conformalizer(base)
        mapie.conformalize(x_ca, y_ca)
        self._base = base
        self._mapie = mapie
        return self

    def predict_interval(
        self, prices: pd.Series, *, fundamentals: pd.DataFrame | None = None
    ) -> IntervalForecast:
        if self._mapie is None:
            raise RuntimeError("call fit() before predict_interval()")
        baseline = self._baseline(prices)
        feats = self._features(prices, fundamentals, baseline)
        x, idx = feats.to_numpy(), pd.DatetimeIndex(feats.index)
        pred, interval = self._mapie.predict_interval(x)

        point = pd.Series(np.asarray(pred).ravel(), index=idx, name="point")
        lower = pd.Series(interval[:, 0, 0], index=idx, name="lower")
        upper = pd.Series(interval[:, 1, 0], index=idx, name="upper")

        # Keep the point forecast inside its own interval (quantile crossing).
        #
        # CQR fits three *independent* LightGBM quantile models and MAPIE conformalizes
        # only the lower/upper pair, leaving the median model unconstrained relative to
        # it, so the three can cross. Measured 2026-07-28 on the shipped model: on 10 of
        # 30 synthetic seeds the median fell outside its interval (12 `lower > point`
        # and 9 `point > upper` points in total). `lower > upper` never occurred, so the
        # *interval* was always valid and no coverage number is affected; what was
        # violated is the ordering invariant the R2.1 spec and `formulation-uncertainty.md` §R2.1
        # both assert. The old `test_interval_ordering` passed on one lucky seed; it is
        # now swept over seeds so it cannot pass by luck again.
        #
        # Clipping, rather than re-sorting all three, is deliberate: the interval is the
        # object carrying the conformal guarantee and must not move. Only the point is
        # adjusted, and only where it was already inconsistent.
        n_clipped = int(((point < lower) | (point > upper)).sum())
        point = point.clip(lower=lower, upper=upper).rename("point")

        if baseline is not None:
            # Back to price space. Affine with a strictly positive slope, so the three
            # series stay ordered and the interval covers the price exactly as often as
            # the standardized one covered the standardized target (R2.1e).
            point = invert_standardized(point, baseline)
            lower = invert_standardized(lower, baseline)
            upper = invert_standardized(upper, baseline)
        return IntervalForecast(
            point=point,
            lower=lower,
            upper=upper,
            confidence_level=self.confidence_level,
            n_point_clipped=n_clipped,
        )

    def recalibrate(
        self, recent_prices: pd.Series, *, fundamentals: pd.DataFrame | None = None
    ) -> PriceForecaster:
        """Refresh the conformal calibration on a recent window; base models unchanged.

        Rewraps the already-fitted base learner(s) in a new conformal estimator and
        conformalizes *that* on ``recent_prices``. Calling ``conformalize`` again on
        the estimator ``fit`` built raises in MAPIE ("conformalize method already
        called"), which made this method unusable for both methods and left the
        drift module's recalibrate-don't-retrain response unreachable.

        Only the conformal quantile changes: the point forecast is bit-identical
        afterwards, which is what separates this from a refit.
        """
        if self._base is None:
            raise RuntimeError("call fit() before recalibrate()")
        baseline = self._baseline(recent_prices)
        feats = self._features(recent_prices, fundamentals, baseline)
        y = self._standardize(align_target(recent_prices, feats), baseline)
        mapie = self._conformalizer(self._base)
        mapie.conformalize(feats.to_numpy(), y.to_numpy())
        self._mapie = mapie
        return self
