"""Golden oracles for the anomaly-aware ingestion guard (R1.5b).

Spec: ``docs/specs/R1.5b-ingestion-guard.md`` § "Golden oracles". Hand-constructed
feeds with a *known* fault → the exact expected classification and reason. The
un-fakeable counterpart, for data, to the MILP golden oracles: the corruption is
objective (a gap is a gap), so "catch it and label it" is checked against inputs
the implementation cannot fudge.

No new math; no committed real data (synthetic feeds only).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bess.data.fixtures import PRICE_COL, synthetic_day_ahead
from bess.data.ingestion_guard import (
    FeedStatus,
    IngestionGuardError,
    classify_series,
    guarded_fetch,
)

BAND = (-600.0, 5000.0)
MAX_REPEAT = 8  # 8 h at 60-min resolution (max_flat_hours = 8)


def _clean_day(seed: int = 1) -> pd.Series:
    """One synthetic, varying, in-band hourly day → healthy by construction."""
    return synthetic_day_ahead(days=1, seed=seed)


def _varying_low_day() -> pd.Series:
    """A legitimate solar-glut day: real negatives/zeros that still *vary* hourly.

    The domain trap — this MUST classify HEALTHY. A naive 'flag zero / flag
    negative' check would misread it as corruption and fall back to stale prices.
    """
    idx = pd.date_range("2024-06-01", periods=24, freq="1h", tz="UTC")
    vals = np.array(
        [5, 4, 3, 2, 1, 0, -1, -3, -6, -9, -12, -15,
         -12, -8, -4, -1, 0, 2, 6, 12, 20, 15, 10, 7],
        dtype=float,
    )  # fmt: skip
    return pd.Series(vals, index=idx, name=PRICE_COL)


def _classify(series: pd.Series):
    return classify_series(
        series, sanity_band=BAND, max_repeat=MAX_REPEAT, expected_slots_per_day=None
    )


# ── content classification (classify_series) ──────────────────────────────────


def test_oracle1_clean_day_is_healthy():
    status, reason = _classify(_clean_day())
    assert status is FeedStatus.HEALTHY
    assert reason is None


def test_oracle2_stuck_zero_block_is_anomaly_stuck_feed():
    s = _clean_day().copy()
    s.iloc[5 : 5 + MAX_REPEAT] = 0.0  # a bit-identical frozen run
    status, reason = _classify(s)
    assert status is FeedStatus.ANOMALY
    assert reason == "stuck_feed"  # the *repetition* fires, not the zero


def test_oracle3_interior_gap_is_anomaly_schema():
    s = _clean_day()
    s = s.drop(s.index[10])  # a missing interior slot → irregular grid
    status, reason = _classify(s)
    assert status is FeedStatus.ANOMALY
    assert reason.startswith("schema:")


def test_oracle4_out_of_band_spike_is_anomaly():
    s = _clean_day().copy()
    s.iloc[12] = 9999.0  # above the EPEX SDAC max + headroom
    status, reason = _classify(s)
    assert status is FeedStatus.ANOMALY
    assert reason == "out_of_band"


def test_oracle5_varying_negative_day_is_healthy():
    # anti-false-positive: legitimate negatives/zeros that vary → healthy.
    status, reason = _classify(_varying_low_day())
    assert status is FeedStatus.HEALTHY
    assert reason is None


# ── end-to-end guard (guarded_fetch): fetch → classify → fallback → log ────────


def test_oracle6_timeout_falls_back_to_last_known_good():
    lkg = _clean_day(seed=2)

    def boom() -> pd.Series:
        raise TimeoutError("connection timed out")

    res = guarded_fetch(boom, last_known_good=lkg)
    assert res.status is FeedStatus.OUTAGE
    assert res.reason == "timeout"
    assert res.degraded is True
    pd.testing.assert_series_equal(res.prices, lkg)


def test_anomaly_falls_back_and_labels():
    lkg = _clean_day(seed=3)
    bad = _clean_day(seed=4).copy()
    bad.iloc[0:MAX_REPEAT] = 0.0
    res = guarded_fetch(lambda: bad, last_known_good=lkg)
    assert res.status is FeedStatus.ANOMALY
    assert res.reason == "stuck_feed"
    assert res.degraded is True
    pd.testing.assert_series_equal(res.prices, lkg)


def test_healthy_passthrough_untouched():
    good = _clean_day(seed=5)
    res = guarded_fetch(lambda: good, last_known_good=None)
    assert res.status is FeedStatus.HEALTHY
    assert res.degraded is False
    pd.testing.assert_series_equal(res.prices, good)


def test_no_last_known_good_raises_hard_stop():
    bad = _clean_day().copy()
    bad.iloc[0:MAX_REPEAT] = 0.0
    with pytest.raises(IngestionGuardError):
        guarded_fetch(lambda: bad, last_known_good=None)


def test_outage_and_anomaly_are_distinct_in_logs(caplog):
    lkg = _clean_day(seed=6)
    stuck = _clean_day(seed=7).copy()
    stuck.iloc[0:MAX_REPEAT] = 0.0
    with caplog.at_level("WARNING"):
        guarded_fetch(lambda: (_ for _ in ()).throw(TimeoutError()), last_known_good=lkg)
        guarded_fetch(lambda: stuck, last_known_good=lkg)
    text = caplog.text
    assert "outage" in text and "anomaly" in text  # the two classes are grep-distinct
