"""forecaster — probabilistic price model (LightGBM + conformal intervals).

Feeds ``scenarios`` / ``stochastic``. (R2.1)

``make_features`` is pure pandas (no LightGBM/MAPIE); ``PriceForecaster`` and
``walk_forward_coverage`` require the optional ``forecast`` dependency group and are
imported lazily so importing this package never hard-fails without the group.
"""

from __future__ import annotations

from bess.forecaster.features import DEFAULT_LAGS, align_target, make_features

__all__ = [
    "DEFAULT_LAGS",
    "IntervalForecast",
    "PriceForecaster",
    "align_target",
    "make_features",
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
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
