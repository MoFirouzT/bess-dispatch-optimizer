"""Anomaly-aware ingestion circuit breaker — the second breaker (R1.4c).

Spec: ``docs/specs/R1.4c-ingestion-guard.md``. Where the R1.5 breaker wraps the
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

# Stuck-feed thresholds, in wall-clock hours (converted to a slot count per the
# series resolution), so they survive the 60→15-min switch.
#
# A bit-identical run means the market cleared at the *same cent* repeatedly. That is
# only plausible at a **structural focal point** of the bid stack, where the merit
# order has a genuine flat step:
#   * €0.00 — the natural zero bid. When supply exceeds demand the clearing price
#     collapses onto it, so many hours clear at exactly 0.00.
#   * the SDAC technical floor / cap — the price cannot cross them, so it pins there
#     under scarcity. (Principled, not observed in NL/BE 2024; included so a genuine
#     scarcity pin is not misread as a freeze.)
# At any *other* value the same cent recurring is a frozen feed: prices are quoted to
# the cent and move continuously, so an arbitrary value repeating for hours has
# negligible probability.
#
# Measured across NL + BE full-year 2024: every run >= 3 h sits at |p| <= €0.01
# (8 h and 7 h at 0.00, 3 h at 0.00, 3 h at -0.01), while runs at arbitrary values
# never exceed 2 h. Negative prices below zero are a different regime (must-run units
# paying to stay on) and vary continuously: -50.00, -39.79, -27.30 are all distinct.
# So the discriminator is the *value*, not the run length.
FOCAL_PRICE_EPS: float = 0.01  # prices are quoted to the cent

# Minimum slots on each side before an irregular grid is called a resolution change
# rather than a cluster of gaps. The real event (2025-10 SDAC PT60M→PT15M) had 46 and
# 104; a gap is one odd step, not a regime.
_MIN_RESOLUTION_SEGMENT: int = 4

# Non-focal: 2x the observed 2 h maximum. Tight by design — an arbitrary cent
# repeating is implausible a priori, so this catches a freeze faster than any
# length-only rule could without false-positiving on the zero runs.
DEFAULT_MAX_FLAT_HOURS: float = 4.0

# Focal: 3x the observed 8 h maximum. Zero-price runs grow with solar buildout, so
# this is deliberately loose; a full day pinned at exactly one focal price is still
# worth a human look (and catches an all-zeros feed).
DEFAULT_MAX_FOCAL_FLAT_HOURS: float = 24.0


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


def _irregular_grid_reason(steps: np.ndarray) -> str:
    """Name *why* a grid is irregular: a **resolution change**, or a **gap**.

    A resolution change is a regime change: the series splits into two contiguous
    segments, each internally regular, at different steps. That is what the 2025-10
    SDAC switch from PT60M to PT15M looks like (46 hourly steps then 104 quarter-hourly
    ones), and it is **not missing data** — the feed is complete and correct, it simply
    is not the single-frequency series the internal schema can carry. Calling it a
    ``gap`` sends an operator hunting for timestamps that were never absent.

    A gap is an isolated odd step in an otherwise uniform grid: a slot the feed failed
    to publish.

    Deliberately conservative: anything that is not cleanly two long regimes is called
    a gap. Both classify ANOMALY regardless, so a misnamed edge case costs a log line,
    not a wrong decision.
    """
    runs: list[int] = []
    start = 0
    for i in range(1, len(steps) + 1):
        if i == len(steps) or steps[i] != steps[i - 1]:
            runs.append(i - start)
            start = i
    if len(runs) == 2 and all(count >= _MIN_RESOLUTION_SEGMENT for count in runs):
        return "schema:resolution_change"
    return "schema:gap"


def is_focal_price(value: float, sanity_band: tuple[float, float] = DEFAULT_SANITY_BAND) -> bool:
    """Is ``value`` a structural focal point the market plausibly clears at repeatedly?

    Zero (the natural zero bid) or either technical band edge. A bit-identical run at
    a focal price is market behaviour; at any other value it is a frozen feed.
    """
    lo, hi = sanity_band
    return (
        abs(value) <= FOCAL_PRICE_EPS
        or value <= lo + FOCAL_PRICE_EPS
        or value >= hi - FOCAL_PRICE_EPS
    )


def _longest_runs_by_focality(
    values: np.ndarray, sanity_band: tuple[float, float]
) -> tuple[int, int]:
    """Longest bit-identical run at a non-focal value, and at a focal value.

    Returns ``(longest_nonfocal, longest_focal)``. Splitting the runs is the whole
    point of the shape check: a 24 h run at €0.00 and a 4 h run at €73.07 are judged
    against different thresholds because only one of them is plausible market
    behaviour.
    """
    if values.size == 0:
        return 0, 0
    longest_nonfocal = longest_focal = 0
    run = 1
    for i in range(1, values.size + 1):
        if i < values.size and values[i] == values[i - 1]:
            run += 1
            continue
        # The run ended at i-1; attribute it by the value it repeated.
        if is_focal_price(float(values[i - 1]), sanity_band):
            longest_focal = max(longest_focal, run)
        else:
            longest_nonfocal = max(longest_nonfocal, run)
        run = 1
    return longest_nonfocal, longest_focal


def classify_series(
    series: pd.Series,
    *,
    sanity_band: tuple[float, float] = DEFAULT_SANITY_BAND,
    max_repeat: int = 4,
    max_focal_repeat: int = 24,
    expected_slots_per_day: int | None = None,
) -> tuple[FeedStatus, str | None]:
    """Classify an already-fetched series as HEALTHY or ANOMALY (no I/O).

    Transport/outage is decided by :func:`guarded_fetch` before this runs, so this
    pure classifier returns only HEALTHY or ANOMALY. Checks fire in a fixed
    precedence — ``empty`` → ``short`` → ``non_finite`` → ``schema:*`` (structural)
    → ``out_of_band`` → ``stuck_feed`` — and the first match names the reason.

    The stuck-feed check is **shape-aware**, not a single length cap: a run is judged
    against ``max_repeat`` or ``max_focal_repeat`` depending on whether it repeats a
    structural focal price (see :func:`is_focal_price`). Both are resolved slot counts
    (the config layer converts wall-clock hours via the series resolution).
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
        steps = idx.to_series().diff().dropna().to_numpy()
        if len(np.unique(steps)) != 1:
            return FeedStatus.ANOMALY, _irregular_grid_reason(steps)

    # Content checks — level-independent: legitimate negatives/zeros are in-band and
    # vary, so only genuine pathology fires.
    if (values < lo).any() or (values > hi).any():
        return FeedStatus.ANOMALY, "out_of_band"

    # Stuck feed, shape-aware: an arbitrary cent repeating is implausible fast; a
    # focal price (0.00, band edges) legitimately repeats for many hours.
    nonfocal_run, focal_run = _longest_runs_by_focality(values, sanity_band)
    if nonfocal_run >= max_repeat or focal_run >= max_focal_repeat:
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
    *,
    detail: str | None = None,
) -> GuardResult:
    """Log the degradation and substitute the last-known-good series, or hard-stop.

    ``reason`` is the stable, greppable token; ``detail`` carries the underlying
    diagnosis (e.g. the validator's message) into the log and the hard-stop error.
    Without it the operator sees only the token, which for a fetch-path schema
    failure is the same string for every cause: exactly the conflation ADR-0012
    exists to prevent.
    """
    _logger.warning(
        "ingestion feed degraded: status=%s reason=%s%s",
        status.value,
        reason,
        f" detail={detail}" if detail else "",
    )
    prices = _resolve_last_known_good(last_known_good)
    if prices is None:
        raise IngestionGuardError(
            f"feed classified {status.value} ({reason}"
            f"{f': {detail}' if detail else ''}) and no last-known-good "
            "series is available to fall back to"
        )
    return GuardResult(status=status, prices=prices, reason=reason, degraded=True)


def guarded_fetch(
    fetch_fn: Callable[[], pd.Series],
    *,
    last_known_good: Callable[[], pd.Series] | pd.Series | None = None,
    sanity_band: tuple[float, float] = DEFAULT_SANITY_BAND,
    max_flat_hours: float = DEFAULT_MAX_FLAT_HOURS,
    max_focal_flat_hours: float = DEFAULT_MAX_FOCAL_FLAT_HOURS,
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
        # The token stays stable and greppable; the validator's message is the only
        # thing that says *which* rule failed (tz, gap, duplicate, resolution change,
        # window truncation), so it must not be thrown away. Naming the token after
        # the Python type instead, as this once did, bucketed every cause together.
        return _degraded(FeedStatus.ANOMALY, "schema:invalid", last_known_good, detail=str(exc))
    except Exception as exc:  # transport-shaped failure
        return _degraded(
            FeedStatus.OUTAGE, _outage_reason(exc), last_known_good, detail=str(exc) or None
        )

    status, reason = classify_series(
        series,
        sanity_band=sanity_band,
        max_repeat=_resolve_max_repeat(series, max_flat_hours),
        max_focal_repeat=_resolve_max_repeat(series, max_focal_flat_hours),
        expected_slots_per_day=expected_slots_per_day,
    )
    if status is FeedStatus.HEALTHY:
        return GuardResult(status=status, prices=series, reason=None, degraded=False)
    return _degraded(status, reason, last_known_good)


def compose_provenance(feed_status: FeedStatus, solve_mode: str) -> str:
    """Combine ingestion status and solver mode into one overall provenance label.

    The shared degradation vocabulary of ADR-0013: a schedule solved on non-healthy
    (e.g. stale fallback) data is degraded *regardless* of the solver mode, so a
    consumer cannot read ``mode="optimal"`` and conclude the result is trustworthy.
    Returns ``"healthy"`` only when the feed is healthy *and* the solver returned an
    optimum. ``solve_mode`` is an opaque string (e.g. R1.5's ``"optimal"`` /
    ``"fallback_greedy"``), so this stays in the ``data`` leaf with no upward import.
    """
    parts: list[str] = []
    if feed_status is not FeedStatus.HEALTHY:
        parts.append(f"data:{feed_status.value}")
    if solve_mode != "optimal":
        parts.append(f"solve:{solve_mode}")
    if not parts:
        return "healthy"
    return "degraded (" + ", ".join(parts) + ")"
