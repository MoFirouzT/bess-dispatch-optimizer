"""Integration — R1.4c ingestion guard sanity-checked against real ENTSO-E prices.

Contract: docs/specs/R1.4c-ingestion-guard.md § "Acceptance gate" (the token-gated
integration check) and § "Config": confirm on a *full year* of real NL and BE
day-ahead data that
  (a) a genuine feed classifies HEALTHY — the guard does not false-positive on the
      real price shape (legitimate negatives/zeros, day-to-day repeats);
  (b) the longest legitimate bit-identical run stays **under** the resolved
      `max_repeat`, so the stuck-feed check has real headroom, and the slice is
      non-vacuous (it still contains a long legitimate run, so (b) can fail); and
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
from entsoe import EntsoePandasClient

from bess.data.entsoe import fetch_day_ahead
from bess.data.fixtures import PRICE_COL
from bess.data.ingestion_guard import (
    DEFAULT_MAX_FLAT_HOURS,
    DEFAULT_MAX_FOCAL_FLAT_HOURS,
    FeedStatus,
    _longest_runs_by_focality,
    _resolve_max_repeat,
    classify_series,
    guarded_fetch,
    is_focal_price,
)

BAND = (-600.0, 5000.0)

pytestmark = pytest.mark.integration

requires_token = pytest.mark.skipif(
    not os.environ.get("ENTSOE_API_TOKEN"),
    reason="ENTSOE_API_TOKEN not set — live ENTSO-E integration test skipped (never runs in CI)",
)


def _last_complete_month() -> tuple[pd.Timestamp, pd.Timestamp]:
    """The most recent fully-published calendar month, in UTC."""
    first_of_this_month = pd.Timestamp.now(tz="UTC").normalize().replace(day=1)
    return (first_of_this_month - pd.Timedelta(days=1)).replace(day=1), first_of_this_month


@requires_token
def test_real_sdac_resolution_switch_is_labelled_a_resolution_change():
    """The real 2025-10 SDAC PT60M→PT15M switch must be named for what it is.

    A window straddling the switch is genuinely irregular, so the guard is right to
    refuse it: the engine cannot consume a mixed-resolution series. But nothing is
    *missing* — the feed is complete and correct, the market changed MTU. Reporting
    `schema:gap` sent an operator hunting for timestamps that were never absent.

    Uses the raw entsoe-py client rather than `fetch_day_ahead`, because the loader
    validates and raises before the classifier would ever see the series (in that
    production path the guard reports `schema:invalid` and the validator's message
    reaches the log as `detail=`). This is the only way to exercise the classifier
    against the real switch.
    """
    client = EntsoePandasClient(api_key=os.environ["ENTSOE_API_TOKEN"])
    raw = client.query_day_ahead_prices(
        "NL", start=pd.Timestamp("2025-09-29", tz="UTC"), end=pd.Timestamp("2025-10-02", tz="UTC")
    )
    s = raw.tz_convert("UTC").sort_index().astype(float)
    s.name = PRICE_COL

    # The window really does straddle the switch (else this proves nothing).
    steps = set(s.index.to_series().diff().dropna())
    assert steps == {pd.Timedelta(hours=1), pd.Timedelta(minutes=15)}, (
        f"window no longer spans the PT60M→PT15M switch; steps seen: {steps}"
    )

    status, reason = classify_series(s)
    assert status is FeedStatus.ANOMALY  # correct: the engine cannot consume it
    assert reason == "schema:resolution_change", f"real MTU switch mislabelled as {reason}"


@requires_token
@pytest.mark.parametrize("zone", ["NL", "BE"])
def test_sanity_band_still_matches_the_live_market(zone):
    """Watchdog: has the sanity band gone **stale** against the market it encodes?

    The band is a *technical* SDAC bound, so real prices cannot breach a correctly-set
    one. It therefore only fails if the band is wrong — which is the point, because
    `[-600, 5000]` encodes a spec claim dated 2026-05-28 that nothing else
    re-validates. If SDAC moves a limit, this notices, instead of production
    discovering it as a false `out_of_band` that substitutes stale prices.

    Deliberately on the **last complete month**, not a historical year: 2024 prices are
    frozen, so asserting they sit in the band is a fact that can never regress and
    would be a vacuous watchdog.
    """
    start, end = _last_complete_month()
    prices = fetch_day_ahead(zone, start, end)
    values = prices.to_numpy(dtype=float)
    lo, hi = BAND

    assert np.all(values >= lo) and np.all(values <= hi), (
        f"{zone} {start:%Y-%m}: real prices [{values.min():.2f}, {values.max():.2f}] fall "
        f"outside the sanity band [{lo}, {hi}] — the SDAC limits it encodes have moved"
    )

    # Headroom, as an early warning. Negative prices deepen as renewables build out:
    # BE's annual minimum went −140 (2024) → −462 (2025). A floor the market is
    # closing on is the signal to re-check the current SDAC limit, before a genuine
    # price breaches it and the guard starts rejecting real data.
    assert values.min() > lo + 50.0, (
        f"{zone} {start:%Y-%m}: minimum {values.min():.2f} is within €50 of the band "
        f"floor {lo} — real prices are approaching it; re-check the current SDAC limit"
    )
    assert values.max() < hi - 50.0, (
        f"{zone} {start:%Y-%m}: maximum {values.max():.2f} is within €50 of the band cap "
        f"{hi} — scarcity may have escalated the SDAC cap past the one step assumed"
    )


@requires_token
@pytest.mark.parametrize("zone", ["NL", "BE"])
def test_real_feed_is_healthy_with_stuck_feed_headroom(zone):
    """A **full year** of real prices, deliberately: the headroom check below is only
    meaningful on a slice that actually contains a long legitimate flat run.

    This test previously fetched one week (2024-03-01..03-08), whose longest
    bit-identical run is 1 hour — so `longest_real_run < max_repeat` passed
    trivially and could not fail. That vacuous check is what let the default sit
    exactly on the real-world maximum: NL *and* BE both cleared at €0.00 for 8
    consecutive hours on 2024-03-24 (a sunny Sunday solar glut), and the old 8 h
    default fired on it, classifying real prices as a stuck feed. Both zones are
    checked because that lockstep freeze is precisely what proves it is market
    coupling rather than a frozen feed.
    """
    prices = fetch_day_ahead(
        zone, pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC")
    )

    # (a) The genuine feed passes clean — no false positive on the real price shape.
    # With the old 8 h default this fails on the 2024-03-24 zero run.
    result = guarded_fetch(lambda: prices, last_known_good=prices)
    assert result.status is FeedStatus.HEALTHY, (
        f"{zone} 2024 real feed classified {result.status.value} ({result.reason}) — "
        "the guard is false-positiving on legitimate market data"
    )
    assert not result.degraded
    assert result.reason is None

    # (b) Both shape-aware bounds have headroom against the real feed, measured
    # separately: the value, not the length, decides which bound a run answers to.
    max_repeat = _resolve_max_repeat(prices, DEFAULT_MAX_FLAT_HOURS)
    max_focal_repeat = _resolve_max_repeat(prices, DEFAULT_MAX_FOCAL_FLAT_HOURS)
    nonfocal_run, focal_run = _longest_runs_by_focality(prices.to_numpy(dtype=float), BAND)
    assert nonfocal_run < max_repeat, (
        f"{zone}: longest run at an arbitrary value is {nonfocal_run} slots, reaching the "
        f"non-focal threshold {max_repeat} — real prices repeat an arbitrary cent longer "
        "than the guard assumes, so the bound is too tight"
    )
    assert focal_run < max_focal_repeat, (
        f"{zone}: longest run at a focal price is {focal_run} slots, reaching the focal "
        f"threshold {max_focal_repeat} — real zero-price runs have outgrown the allowance"
    )

    # (b2) ...and the slice is *non-vacuous*: it must still contain a long legitimate
    # focal run, or (b) proves nothing. Guards against shrinking this window back to
    # one that cannot fail — the bug this test used to have. Observed in 2024: an 8 h
    # zero run in both zones, and never more than 2 h at any arbitrary value.
    assert focal_run >= 6, (
        f"{zone}: longest focal run is only {focal_run} slots — this slice no longer "
        "exercises the focal allowance, so the headroom check above is vacuous"
    )

    # (b3) The discriminator itself, on real data: arbitrary values genuinely do not
    # repeat for long, which is *why* the non-focal bound can be tight. If this ever
    # fails, the focal/non-focal split is the wrong model for this market.
    assert nonfocal_run < focal_run, (
        f"{zone}: longest arbitrary-value run ({nonfocal_run}) is not shorter than the "
        f"longest focal run ({focal_run}) — the shape check's premise does not hold here"
    )

    # (c) Freeze a real slice at a real *arbitrary* (non-focal) price and confirm the
    # guard catches it. The median is a genuine price from this feed, so the frozen
    # series is real-shaped everywhere except the freeze.
    frozen_value = float(prices.median())
    assert not is_focal_price(frozen_value, BAND), f"{zone}: median {frozen_value} is focal"
    frozen = prices.copy()
    frozen.iloc[:max_repeat] = frozen_value
    status, reason = classify_series(
        frozen, max_repeat=max_repeat, max_focal_repeat=max_focal_repeat
    )
    assert status is FeedStatus.ANOMALY
    assert reason == "stuck_feed"

    # (d) The same freeze at the €0.00 focal price must NOT fire: the real-data
    # counterpart of golden oracle 2b, and the whole reason the shape check exists.
    # This is the case that used to be a false positive on 2024-03-24.
    zeroed = prices.copy()
    zeroed.iloc[:max_repeat] = 0.0
    status, reason = classify_series(
        zeroed, max_repeat=max_repeat, max_focal_repeat=max_focal_repeat
    )
    assert status is FeedStatus.HEALTHY, (
        f"{zone}: a {max_repeat}-slot run at €0.00 classified {status.value} ({reason}) — "
        "the guard is treating legitimate zero-price clearing as a frozen feed"
    )

    # (e) The real prices sit inside the EPEX SDAC sanity band (no out_of_band flag).
    # Note this is a *historical* year, so it is a fixed fact that cannot regress — it
    # guards the classifier, not the band. Watching the band for staleness needs
    # current data: see test_sanity_band_still_matches_the_live_market below.
    lo, hi = BAND
    values = prices.to_numpy(dtype=float)
    assert np.all(values >= lo) and np.all(values <= hi)
