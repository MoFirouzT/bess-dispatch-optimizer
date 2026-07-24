"""Scenario generation: residual-path bootstrap off the R2.1 forecast (R2.2).

See ``docs/formulation.md`` § R2.2 and ADR-0017. A scenario is a full-horizon
price path ``π^(s) = μ̂ + r^(j)`` where ``r^(j)`` is a whole-day forecast-error
vector resampled (with replacement) from the forecaster's residual history.
Resampling whole vectors preserves the intra-day error correlation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from bess.scenarios.tail import ConditionalTailModel, TailModel, apply_tail

if TYPE_CHECKING:  # avoid importing the LightGBM/MAPIE-backed forecaster at runtime
    from bess.forecaster.forecast import IntervalForecast

_PROB_ATOL = 1e-9


@dataclass(frozen=True)
class ScenarioSet:
    """A discrete distribution over price paths.

    ``paths`` has shape ``(S, T)`` (S scenarios over the T-hour horizon, €/MWh
    grid-side); ``probs`` has shape ``(S,)``, non-negative and summing to 1;
    ``index`` are the T target UTC timestamps the paths are indexed on.
    """

    paths: np.ndarray
    probs: np.ndarray
    index: pd.DatetimeIndex

    def __post_init__(self) -> None:
        paths = np.asarray(self.paths, dtype=float)
        probs = np.asarray(self.probs, dtype=float)
        if paths.ndim != 2:
            raise ValueError(f"paths must be 2-D (S, T); got shape {paths.shape}")
        s, t = paths.shape
        if probs.shape != (s,):
            raise ValueError(f"probs must have shape ({s},); got {probs.shape}")
        if len(self.index) != t:
            raise ValueError(f"index length {len(self.index)} != horizon {t}")
        if (probs < -_PROB_ATOL).any():
            raise ValueError("probs must be non-negative")
        if not np.isclose(probs.sum(), 1.0, atol=_PROB_ATOL):
            raise ValueError(f"probs must sum to 1; got {probs.sum()}")
        object.__setattr__(self, "paths", paths)
        object.__setattr__(self, "probs", probs)

    @property
    def n_scenarios(self) -> int:
        return self.paths.shape[0]

    @property
    def horizon(self) -> int:
        return self.paths.shape[1]


def generate_scenarios(
    forecast: IntervalForecast,
    residuals: np.ndarray,
    *,
    n: int,
    seed: int,
    tail: TailModel | ConditionalTailModel | None = None,
    tail_covariate: np.ndarray | None = None,
) -> ScenarioSet:
    """Residual-path bootstrap (ADR-0017), optionally with an extreme-value tail (R2.2b/c).

    ``forecast`` supplies the point path via ``forecast.point`` (a ``pd.Series``
    indexed by target timestamp). ``residuals`` is an ``(M, T)`` matrix of
    historical whole-day error vectors (``actual − forecast``) from the
    forecaster's calibration history. Returns ``n`` equiprobable paths, each the
    point forecast plus one resampled error vector.

    When ``tail`` is given (a fitted :class:`~bess.scenarios.tail.TailModel`), each
    resampled residual's exceedances over the tail threshold are spliced with GPD
    draws, so scenarios can exceed the historical-maximum residual (peaks-over-
    threshold; spec R2.2b). A :class:`~bess.scenarios.tail.ConditionalTailModel`
    (R2.2c) additionally takes ``tail_covariate`` (the target day's per-hour residual
    load, length ``T``) so the spike scale rises on tight-margin hours. ``tail=None``
    is byte-identical to the plain bootstrap: the tail draws come from the same
    generator *after* the resample indices, so the bootstrap itself is unchanged.
    """
    if n < 1:
        raise ValueError(f"n must be >= 1; got {n}")
    point_series = forecast.point
    point = np.asarray(point_series, dtype=float)
    index = pd.DatetimeIndex(point_series.index)
    resid = np.asarray(residuals, dtype=float)
    if resid.ndim != 2 or resid.shape[1] != point.shape[0]:
        raise ValueError(
            f"residuals must be (M, {point.shape[0]}) to match the {point.shape[0]}-hour "
            f"forecast; got {resid.shape}"
        )
    if resid.shape[0] < 1:
        raise ValueError("residuals must contain at least one row to resample")

    rng = np.random.default_rng(seed)
    draws = rng.integers(0, resid.shape[0], size=n)
    resid_draws = resid[draws]
    if tail is not None:
        resid_draws = apply_tail(resid_draws, tail, rng, covariate=tail_covariate)
    paths = point[None, :] + resid_draws
    probs = np.full(n, 1.0 / n)
    return ScenarioSet(paths=paths, probs=probs, index=index)
