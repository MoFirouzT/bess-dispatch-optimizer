"""forecaster — probabilistic price model (LightGBM + conformal intervals).

Feeds ``scenarios`` / ``stochastic``. (R2.1)

``make_features`` and the ``conformal`` primitives are pure numpy/pandas (no
LightGBM/MAPIE); ``PriceForecaster``, ``walk_forward_coverage``,
``sequential_coverage`` and ``search_sharpest`` require the optional ``forecast``
dependency group and are imported lazily so importing this package never hard-fails
without the group.
"""

from __future__ import annotations

from bess.forecaster.conformal import (
    AciState,
    aci_bound,
    aci_realized_gap,
    aci_update,
    changepoint_gap_bound,
    cqr_score,
    decay_weights,
    drift_gap_bound,
    split_score,
    weighted_quantile,
)
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
    "AciState",
    "CoverageResult",
    "SequentialCoverage",
    "DriftMonitor",
    "DriftReport",
    "DriftStatus",
    "Fold",
    "IntervalForecast",
    "PriceForecaster",
    "SharpnessCandidate",
    "SharpnessSearch",
    "aci_bound",
    "aci_realized_gap",
    "aci_update",
    "align_target",
    "changepoint_gap_bound",
    "classify_drift",
    "cqr_score",
    "coverage_by_hour",
    "coverage_ci",
    "decay_weights",
    "drift_gap_bound",
    "invert_standardized",
    "make_features",
    "pinball_loss",
    "psi",
    "rolling_baseline",
    "rolling_origin_folds",
    "search_sharpest",
    "seasonal_naive",
    "seasonal_naive_forecast",
    "sequential_coverage",
    "split_score",
    "walk_forward_coverage",
    "weighted_quantile",
]


def __getattr__(name: str) -> object:
    # Lazy: only pull in the LightGBM/MAPIE-backed API when actually requested.
    if name in ("PriceForecaster", "IntervalForecast"):
        from bess.forecaster.forecast import IntervalForecast, PriceForecaster

        return {"PriceForecaster": PriceForecaster, "IntervalForecast": IntervalForecast}[name]
    if name in ("walk_forward_coverage", "sequential_coverage", "SequentialCoverage"):
        from bess.forecaster import evaluate

        return getattr(evaluate, name)
    if name in ("search_sharpest", "SharpnessSearch", "SharpnessCandidate"):
        from bess.forecaster import tune

        return getattr(tune, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
