"""Rolling forecast-drift monitor (R2.1b) — regime shift vs. model staleness.

Spec: ``docs/specs/R2.1b-drift-monitor.md``. Watches the R2.1 forecaster's trailing
accuracy and, when it degrades, classifies *why*:

- **regime shift** — the market genuinely moved; the input distribution shifted (high
  PSI) and a naive baseline degrades too, so the model is not specifically at fault;
- **model staleness** — this model decayed relative to a naive seasonal baseline
  (``forecaster_MAE / naive_MAE`` high), while inputs are stable → retrain.

Precedence (ADR-0015): staleness is checked first — even under a regime shift a
healthy model should degrade no worse than naive, so being materially worse than
naive is model-specific decay regardless of input movement.

Pure numpy/pandas: no LightGBM/MAPIE, so these gates run without the ``forecast``
dependency group. The monitor takes plain arrays (or an ``IntervalForecast``'s
fields), so it is decoupled from a live forecaster.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import pandas as pd

_logger = logging.getLogger(__name__)

DEFAULT_SEASON = 168  # hours; weekly seasonal-naive captures weekday/weekend structure
DEFAULT_PSI_WARN = 0.2  # conventional "significant distribution shift" threshold
DEFAULT_STALENESS_RATIO = 1.3  # forecaster ≥30% worse than naive ⇒ model-specific decay
DEFAULT_CONFIDENCE_LEVEL = 0.9  # nominal interval coverage inherited from the forecaster
DEFAULT_COVERAGE_TOL = 0.10  # breach when empirical ≤ nominal − tol (wider than R2.1's ±0.05)
DEFAULT_MIN_COVERAGE_SAMPLES = 100  # below this, coverage stays informational (small-window noise)


class DriftStatus(StrEnum):
    HEALTHY = "healthy"
    REGIME_SHIFT = "regime_shift"
    STALENESS = "staleness"
    MISCALIBRATION = "miscalibration"  # intervals under-cover: recalibrate, don't retrain


@dataclass(frozen=True, eq=False)
class DriftReport:
    """One trailing-window drift assessment."""

    status: DriftStatus
    forecaster_mae: float
    naive_mae: float
    error_ratio: float
    psi: float
    coverage: float | None
    reason: str | None


def psi(reference: np.ndarray, current: np.ndarray, *, bins: int = 10) -> float:
    """Population Stability Index of ``current`` vs. a ``reference`` distribution.

    Bins are the ``reference``'s quantile edges; values outside the reference range
    fall into the extreme bins. ``psi(x, x) ≈ 0``; it grows as ``current`` drifts
    away. Returns 0.0 for a degenerate (near-constant) reference.
    """
    reference = np.asarray(reference, dtype=float)
    current = np.asarray(current, dtype=float)
    edges = np.unique(np.quantile(reference, np.linspace(0.0, 1.0, bins + 1)))
    if len(edges) < 3:
        return 0.0
    interior = edges[1:-1]
    n_bins = len(interior) + 1
    ref_counts = np.bincount(np.digitize(reference, interior), minlength=n_bins).astype(float)
    cur_counts = np.bincount(np.digitize(current, interior), minlength=n_bins).astype(float)
    eps = 1e-6
    ref_pct = ref_counts / ref_counts.sum() + eps
    cur_pct = cur_counts / cur_counts.sum() + eps
    return float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))


def seasonal_naive_forecast(prices: pd.Series, *, season: int = DEFAULT_SEASON) -> pd.Series:
    """Seasonal-naive forecast ``ŷ_t = π_{t−season}`` (NaN for the first ``season``)."""
    return prices.shift(season).rename("naive")


def classify_drift(
    *,
    forecaster_mae: float,
    naive_mae: float,
    psi_value: float,
    coverage: float | None = None,
    staleness_ratio: float = DEFAULT_STALENESS_RATIO,
    psi_warn: float = DEFAULT_PSI_WARN,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    coverage_tol: float = DEFAULT_COVERAGE_TOL,
    n_coverage: int | None = None,
    min_coverage_samples: int = DEFAULT_MIN_COVERAGE_SAMPLES,
) -> DriftReport:
    """Classify a window from its metrics (ADR-0015 + ADR-0016).

    Precedence: STALENESS (worse than naive) > REGIME_SHIFT (inputs moved) >
    MISCALIBRATION (intervals under-cover) > HEALTHY. Staleness first so model-specific
    decay wins; regime before miscalibration so a genuine input shift keeps its
    attribution even though it also breaks coverage. Miscalibration is one-sided
    (only *under*-coverage) and guarded by ``min_coverage_samples`` to avoid crying
    wolf on small, noisy windows.
    """
    if naive_mae > 0.0:
        ratio = forecaster_mae / naive_mae
    else:
        ratio = float("inf") if forecaster_mae > 0.0 else 1.0

    coverage_breach = (
        coverage is not None
        and (n_coverage is None or n_coverage >= min_coverage_samples)
        and coverage <= confidence_level - coverage_tol
    )

    if ratio >= staleness_ratio:
        status = DriftStatus.STALENESS
        reason = f"error_ratio={ratio:.2f}≥{staleness_ratio} (worse than seasonal-naive)"
    elif psi_value >= psi_warn:
        status = DriftStatus.REGIME_SHIFT
        reason = f"psi={psi_value:.2f}≥{psi_warn} (inputs shifted; model still ~naive)"
    elif coverage_breach:
        status = DriftStatus.MISCALIBRATION
        reason = (
            f"coverage={coverage:.2f}≤{confidence_level - coverage_tol:.2f} "
            f"(intervals under-cover; inputs stable → recalibrate)"
        )
    else:
        status = DriftStatus.HEALTHY
        reason = None
    return DriftReport(
        status=status,
        forecaster_mae=forecaster_mae,
        naive_mae=naive_mae,
        error_ratio=ratio,
        psi=psi_value,
        coverage=coverage,
        reason=reason,
    )


class DriftMonitor:
    """Assess a trailing window of forecasts against realized prices and a naive baseline."""

    def __init__(
        self,
        reference_prices: np.ndarray | pd.Series,
        *,
        season: int = DEFAULT_SEASON,
        psi_warn: float = DEFAULT_PSI_WARN,
        staleness_ratio: float = DEFAULT_STALENESS_RATIO,
        psi_bins: int = 10,
        confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
        coverage_tol: float = DEFAULT_COVERAGE_TOL,
        min_coverage_samples: int = DEFAULT_MIN_COVERAGE_SAMPLES,
    ) -> None:
        self._reference = np.asarray(reference_prices, dtype=float)
        self._season = season
        self._psi_warn = psi_warn
        self._staleness_ratio = staleness_ratio
        self._psi_bins = psi_bins
        self._confidence_level = confidence_level
        self._coverage_tol = coverage_tol
        self._min_coverage_samples = min_coverage_samples

    def naive_from_history(self, prices: pd.Series) -> pd.Series:
        """Seasonal-naive forecast at this monitor's season (a convenience for callers)."""
        return seasonal_naive_forecast(prices, season=self._season)

    def assess(
        self,
        realized: np.ndarray | pd.Series,
        point: np.ndarray | pd.Series,
        naive: np.ndarray | pd.Series,
        *,
        lower: np.ndarray | pd.Series | None = None,
        upper: np.ndarray | pd.Series | None = None,
    ) -> DriftReport:
        """Compute forecaster/naive MAE, PSI (realized vs. reference), coverage, classify."""
        realized = np.asarray(realized, dtype=float)
        point = np.asarray(point, dtype=float)
        naive = np.asarray(naive, dtype=float)
        mask = ~(np.isnan(realized) | np.isnan(point) | np.isnan(naive))
        r, p, nv = realized[mask], point[mask], naive[mask]
        if r.size == 0:
            raise ValueError("no overlapping non-NaN points to assess drift")

        forecaster_mae = float(np.mean(np.abs(r - p)))
        naive_mae = float(np.mean(np.abs(r - nv)))
        psi_value = psi(self._reference, r, bins=self._psi_bins)

        coverage: float | None = None
        n_coverage: int | None = None
        if lower is not None and upper is not None:
            lo = np.asarray(lower, dtype=float)[mask]
            hi = np.asarray(upper, dtype=float)[mask]
            coverage = float(np.mean((r >= lo) & (r <= hi)))
            n_coverage = int(r.size)

        report = classify_drift(
            forecaster_mae=forecaster_mae,
            naive_mae=naive_mae,
            psi_value=psi_value,
            coverage=coverage,
            staleness_ratio=self._staleness_ratio,
            psi_warn=self._psi_warn,
            confidence_level=self._confidence_level,
            coverage_tol=self._coverage_tol,
            n_coverage=n_coverage,
            min_coverage_samples=self._min_coverage_samples,
        )
        if report.status is not DriftStatus.HEALTHY:
            _logger.warning(
                "forecast drift: status=%s reason=%s coverage=%s",
                report.status.value,
                report.reason,
                f"{report.coverage:.2f}" if report.coverage is not None else "n/a",
            )
        return report
