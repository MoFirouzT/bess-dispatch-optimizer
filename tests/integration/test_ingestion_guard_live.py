"""Integration — R1.5b ingestion guard sanity-checked against real ENTSO-E prices.

Contract: docs/specs/R1.5b-ingestion-guard.md § "Acceptance gate" (the token-gated
integration check) and § "Config": confirm on *real* NL day-ahead data that
  (a) a genuine feed classifies HEALTHY — the guard does not false-positive on the
      real price shape (legitimate negatives/zeros, day-to-day repeats);
  (b) the longest legitimate bit-identical run in a real slice stays **under** the
      resolved `max_repeat`, so the stuck-feed check has real headroom; and
  (c) freezing a real slice into a >= `max_repeat` flat run flips it to ANOMALY
      (`stuck_feed`) — the guard catches a real-shaped frozen feed.

Token-gated: skipped unless `ENTSOE_API_TOKEN` is set; deselected in CI via the
`integration` marker. Nothing fetched here is committed — real prices are pulled
at runtime and discarded.

Network setup (this machine): a TLS-intercepting proxy means uv-Python may need the
Keychain roots — see docs/specs/R1.4b-entsoe-loader.md § "Environment note".
"""

import os

import numpy as np
import pandas as pd
import pytest

from bess.data.entsoe import fetch_day_ahead
from bess.data.ingestion_guard import (
    DEFAULT_MAX_FLAT_HOURS,
    FeedStatus,
    _longest_identical_run,
    _resolve_max_repeat,
    classify_series,
    guarded_fetch,
)

pytestmark = pytest.mark.integration

requires_token = pytest.mark.skipif(
    not os.environ.get("ENTSOE_API_TOKEN"),
    reason="ENTSOE_API_TOKEN not set — live ENTSO-E integration test skipped (never runs in CI)",
)


@requires_token
def test_real_feed_is_healthy_with_stuck_feed_headroom():
    # A modest real NL slice (one week, hourly). Fetched live, never committed.
    prices = fetch_day_ahead(
        "NL", pd.Timestamp("2024-03-01", tz="UTC"), pd.Timestamp("2024-03-08", tz="UTC")
    )

    # (a) The genuine feed passes clean — no false positive on the real price shape.
    result = guarded_fetch(lambda: prices, last_known_good=prices)
    assert result.status is FeedStatus.HEALTHY
    assert not result.degraded
    assert result.reason is None

    # (b) The real feed's longest legitimate bit-identical run has headroom under the
    # resolved stuck-feed threshold (8 wall-clock hours → 8 slots at hourly data).
    max_repeat = _resolve_max_repeat(prices, DEFAULT_MAX_FLAT_HOURS)
    longest_real_run = _longest_identical_run(prices.to_numpy(dtype=float))
    assert longest_real_run < max_repeat, (
        f"real feed's longest flat run {longest_real_run} reached the stuck-feed "
        f"threshold {max_repeat} — the wall-clock default is too tight for real data"
    )

    # (c) Freeze a real-shaped stuck run (>= max_repeat in-band identical values) and
    # confirm the guard catches it as a stuck_feed anomaly.
    frozen = prices.copy()
    frozen.iloc[:max_repeat] = float(prices.iloc[0])
    status, reason = classify_series(frozen, max_repeat=max_repeat)
    assert status is FeedStatus.ANOMALY
    assert reason == "stuck_feed"

    # And the real prices sit inside the EPEX SDAC sanity band (no out_of_band flag).
    lo, hi = (-600.0, 5000.0)
    values = prices.to_numpy(dtype=float)
    assert np.all(values >= lo) and np.all(values <= hi)
