"""Composition of the two circuit breakers (R1.4c, ADR-0013).

Spec: ``docs/specs/R1.4c-ingestion-guard.md`` § "Acceptance gate" — the shared
degradation vocabulary, demonstrated end-to-end on synthetic data: a fetch that
falls back to last-known-good, then a solve that is *optimal on that fallback*,
must report a **degraded** overall provenance, not "healthy". This closes the
silent-stale-dispatch hole where ``mode="optimal"`` on stale data reads as fine.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bess.assets.battery import BatterySpec
from bess.backtest.baselines import solve_window
from bess.data.fixtures import PRICE_COL
from bess.data.ingestion_guard import (
    FeedStatus,
    compose_provenance,
    guarded_fetch,
)


def _hourly(values: list[float]) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=len(values), freq="1h", tz="UTC")
    return pd.Series(np.asarray(values, dtype=float), index=idx, name=PRICE_COL)


def test_compose_provenance_rules():
    # Healthy only when feed healthy AND solver optimal.
    assert compose_provenance(FeedStatus.HEALTHY, "optimal") == "healthy"
    # Optimal solve on non-healthy data is still degraded (the whole point).
    assert compose_provenance(FeedStatus.ANOMALY, "optimal") == "degraded (data:anomaly)"
    assert compose_provenance(FeedStatus.OUTAGE, "optimal") == "degraded (data:outage)"
    # A healthy feed but a greedy fallback solve is degraded on the solver side.
    healthy_greedy = compose_provenance(FeedStatus.HEALTHY, "fallback_greedy")
    assert healthy_greedy == "degraded (solve:fallback_greedy)"


def test_degraded_fetch_then_optimal_solve_is_degraded_overall():
    """End-to-end: corrupt fetch → guard falls back → optimal solve → degraded provenance."""
    spec = BatterySpec()  # 1 MWh / 1 MW
    dt = 1.0

    last_known_good = _hourly([10.0, 50.0, 20.0])
    corrupted = _hourly([10.0, 1e6, 20.0])  # an out-of-band spike (fails regardless of length)

    res = guarded_fetch(lambda: corrupted, last_known_good=last_known_good)

    # The guard caught it and substituted trustworthy prices.
    assert res.status is FeedStatus.ANOMALY
    assert res.reason == "out_of_band"
    assert res.degraded is True
    pd.testing.assert_series_equal(res.prices, last_known_good)

    # The solve on the fallback is a genuine optimum...
    schedule, _ = solve_window(res.prices.tolist(), spec, dt)
    assert schedule.termination == "optimal"

    # ...yet the overall provenance is degraded, not "healthy": a solve on stale data
    # is not trustworthy just because the solver succeeded.
    provenance = compose_provenance(res.status, "optimal")
    assert provenance == "degraded (data:anomaly)"
    assert provenance != "healthy"
