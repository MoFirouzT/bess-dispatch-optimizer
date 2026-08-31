"""forecaster — probabilistic price model (LightGBM + conformal intervals).

Feeds ``scenarios`` / ``stochastic``. (R2.1)

``make_features`` is pure pandas (no LightGBM/MAPIE); ``PriceForecaster``,
``walk_forward_coverage`` and ``search_sharpest`` require the optional ``forecast``
dependency group and are imported lazily so importing this package never hard-fails
without the group.
"""

from __future__ import annotations

from bess.forecaster.drift import (
    DriftMonitor,
    DriftReport,
    DriftStatus,
    classify_drift,
    psi,
    seasonal_naive_forecast,
)
from bess.forecaster.evaluate import (
    CoverageResult,
    Fold,
    coverage_by_hour,
    coverage_ci,
    pinball_loss,
    rolling_origin_folds,
    seasonal_naive,
)
from bess.forecaster.features import (
    DEFAULT_LAGS,
    align_target,
    invert_standardized,
    make_features,
    rolling_baseline,
)

__all__ = [
    "DEFAULT_LAGS",
    "CoverageResult",
    "DriftMonitor",
    "DriftReport",
    "DriftStatus",
    "Fold",
    "IntervalForecast",
    "PriceForecaster",
    "SharpnessCandidate",
    "SharpnessSearch",
    "align_target",
    "classify_drift",
    "coverage_by_hour",
    "coverage_ci",
    "invert_standardized",
    "make_features",
    "pinball_loss",
    "psi",
    "rolling_baseline",
    "rolling_origin_folds",
    "search_sharpest",
    "seasonal_naive",
    "seasonal_naive_forecast",
    "walk_forward_coverage",
]


def __getattr__(name: str) -> object:
    # Lazy: only pull in the LightGBM/MAPIE-backed API when actually requested.
    if name in ("PriceForecaster", "IntervalForecast"):
        from bess.forecaster.forecast import IntervalForecast, PriceForecaster

        return {"PriceForecaster": PriceForecaster, "IntervalForecast": IntervalForecast}[name]
    if name == "walk_forward_coverage":
        from bess.forecaster.evaluate import walk_forward_coverage

        return walk_forward_coverage
    if name in ("search_sharpest", "SharpnessSearch", "SharpnessCandidate"):
        from bess.forecaster import tune

        return getattr(tune, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
