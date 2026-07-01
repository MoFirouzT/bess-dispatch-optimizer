"""Anomaly-aware ingestion circuit breaker — the second breaker (R1.5b).

Spec: ``docs/specs/R1.5b-ingestion-guard.md``. Where the R1.5 breaker wraps the
*solve*, this wraps the *fetch*: every price-series fetch is classified

- ``HEALTHY`` — passes through untouched;
- ``OUTAGE`` — transport failure (timeout, connection, 5xx): no present data;
- ``ANOMALY`` — present-but-untrustworthy data (stuck feed, gap, duplicate,
  non-finite, out-of-band), which is the *more* dangerous case because it fails
  silently.

On either failure class the guard falls back to the last-known-good cached
series and logs the specific check that fired, so an operator sees *which layer*
failed (ADR-0012). A schedule later computed on a substituted series is degraded,
not healthy — the shared vocabulary that lets the two breakers compose (ADR-0013).

**The domain trap (designed-in):** zero and negative day-ahead prices are
legitimate in BE/NL (high-renewable windows). The checks therefore key on feed
*pathology* (a bit-identical frozen run, a grid gap, a value outside the EPEX
SDAC clearing-price limits), never on price *level* — a real solar-glut day must
stay HEALTHY, enforced by an anti-false-positive property test.

``data`` is a leaf package: this imports only stdlib, numpy/pandas, and its
sibling ``bess.data.fixtures`` — nothing else in ``bess`` (import-linter).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import pandas as pd

_logger = logging.getLogger(__name__)

# Default sanity band = EPEX SDAC harmonised clearing-price limits + headroom:
# min −600 €/MWh (from 2026-05-28), max 4000 €/MWh base + one +1000 escalation
# step. A value outside this cannot be a real day-ahead clearing price. This is a
# market technical bound, not the year-specific §5 revenue band (spec / ADR-0012).
DEFAULT_SANITY_BAND: tuple[float, float] = (-600.0, 5000.0)

# Stuck-feed threshold in wall-clock hours (converted to a slot count per the
# series resolution), so it survives the 60→15-min switch. A stuck feed is frozen
# indefinitely, so 8 h catches it without firing on a flat-but-real overnight run.
DEFAULT_MAX_FLAT_HOURS: float = 8.0


class FeedStatus(StrEnum):
    """Classification of one price-series fetch."""

    HEALTHY = "healthy"
    OUTAGE = "outage"
    ANOMALY = "anomaly"


@dataclass(frozen=True, eq=False)
class GuardResult:
    """The outcome of a guarded fetch (a leaf-local value object; consumers read it).

    ``prices`` is the fetched series when HEALTHY, or the last-known-good fallback
    when degraded. ``reason`` names the specific check that fired. ``degraded`` is
    True whenever a fallback series was substituted.
    """

    status: FeedStatus
    prices: pd.Series
    reason: str | None
    degraded: bool


class IngestionGuardError(RuntimeError):
    """A fallback was required but no last-known-good series was available."""


def _longest_identical_run(values: np.ndarray) -> int:
    """Length of the longest run of consecutive *bit-identical* values."""
    if values.size == 0:
        return 0
    longest = run = 1
    for i in range(1, values.size):
        if values[i] == values[i - 1]:
            run += 1
            longest = max(longest, run)
        else:
            run = 1
    return longest


def classify_series(
    series: pd.Series,
    *,
    sanity_band: tuple[float, float] = DEFAULT_SANITY_BAND,
    max_repeat: int = 8,
    expected_slots_per_day: int | None = None,
) -> tuple[FeedStatus, str | None]:
    """Classify an already-fetched series as HEALTHY or ANOMALY (no I/O).

    Transport/outage is decided by :func:`guarded_fetch` before this runs, so this
    pure classifier returns only HEALTHY or ANOMALY. Checks fire in a fixed
    precedence — ``empty`` → ``short`` → ``non_finite`` → ``schema:*`` (structural)
    → ``out_of_band`` → ``stuck_feed`` — and the first match names the reason.
    ``max_repeat`` is the resolved slot count (the config layer converts
    ``max_flat_hours`` via the series resolution).
    """
    lo, hi = sanity_band
    idx = series.index
    n = len(series)

    if n == 0:
        return FeedStatus.ANOMALY, "empty"
    if expected_slots_per_day is not None and n < expected_slots_per_day:
        return FeedStatus.ANOMALY, "short"

    values = series.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        return FeedStatus.ANOMALY, "non_finite"

    # Structural (schema) checks — mirror ``validate_price_series`` rules but return
    # a classification instead of raising, so a corrupt grid becomes a labeled
    # anomaly rather than a crash.
    if not isinstance(idx, pd.DatetimeIndex):
        return FeedStatus.ANOMALY, "schema:index"
    if idx.has_duplicates:
        return FeedStatus.ANOMALY, "schema:duplicate"
    if idx.tz is None or str(idx.tz) != "UTC":
        return FeedStatus.ANOMALY, "schema:tz"
    if not idx.is_monotonic_increasing:
        return FeedStatus.ANOMALY, "schema:unsorted"
    if n >= 2:
        steps = idx.to_series().diff().dropna()
        if steps.nunique() != 1:
            return FeedStatus.ANOMALY, "schema:gap"

    # Content checks — level-independent: legitimate negatives/zeros are in-band and
    # vary, so only genuine pathology fires.
    if (values < lo).any() or (values > hi).any():
        return FeedStatus.ANOMALY, "out_of_band"
    if _longest_identical_run(values) >= max_repeat:
        return FeedStatus.ANOMALY, "stuck_feed"

    return FeedStatus.HEALTHY, None


def _resolve_max_repeat(series: pd.Series, max_flat_hours: float) -> int:
    """Convert the wall-clock stuck-feed threshold to a slot count for this series."""
    idx = series.index
    dt_hours = 1.0
    if isinstance(idx, pd.DatetimeIndex) and len(idx) >= 2:
        step = (idx[1] - idx[0]).total_seconds() / 3600.0
        if step > 0:
            dt_hours = step
    return max(1, math.ceil(max_flat_hours / dt_hours))


def _outage_reason(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, ConnectionError):
        return "connection"
    return "transport"


def _resolve_last_known_good(
    last_known_good: Callable[[], pd.Series] | pd.Series | None,
) -> pd.Series | None:
    if last_known_good is None:
        return None
    if callable(last_known_good):
        return last_known_good()
    return last_known_good


def _degraded(
    status: FeedStatus,
    reason: str | None,
    last_known_good: Callable[[], pd.Series] | pd.Series | None,
) -> GuardResult:
    """Log the degradation and substitute the last-known-good series, or hard-stop."""
    _logger.warning("ingestion feed degraded: status=%s reason=%s", status.value, reason)
    prices = _resolve_last_known_good(last_known_good)
    if prices is None:
        raise IngestionGuardError(
            f"feed classified {status.value} ({reason}) and no last-known-good "
            "series is available to fall back to"
        )
    return GuardResult(status=status, prices=prices, reason=reason, degraded=True)


def guarded_fetch(
    fetch_fn: Callable[[], pd.Series],
    *,
    last_known_good: Callable[[], pd.Series] | pd.Series | None = None,
    sanity_band: tuple[float, float] = DEFAULT_SANITY_BAND,
    max_flat_hours: float = DEFAULT_MAX_FLAT_HOURS,
    expected_slots_per_day: int | None = None,
) -> GuardResult:
    """Fetch → classify → (fall back + log) → :class:`GuardResult`.

    ``fetch_fn`` performs the real fetch (wraps R1.4b ``fetch_day_ahead``). Never
    raises on a bad feed: a transport failure classifies OUTAGE, a validation error
    or content pathology classifies ANOMALY, and both fall back to
    ``last_known_good`` and are logged. Raises :class:`IngestionGuardError` only
    when a fallback is needed and none is available (a genuine hard stop).
    """
    try:
        series = fetch_fn()
    except ValueError as exc:  # schema/validation raised inside the fetch
        return _degraded(
            FeedStatus.ANOMALY, f"schema:{type(exc).__name__.lower()}", last_known_good
        )
    except Exception as exc:  # transport-shaped failure
        return _degraded(FeedStatus.OUTAGE, _outage_reason(exc), last_known_good)

    max_repeat = _resolve_max_repeat(series, max_flat_hours)
    status, reason = classify_series(
        series,
        sanity_band=sanity_band,
        max_repeat=max_repeat,
        expected_slots_per_day=expected_slots_per_day,
    )
    if status is FeedStatus.HEALTHY:
        return GuardResult(status=status, prices=series, reason=None, degraded=False)
    return _degraded(status, reason, last_known_good)
