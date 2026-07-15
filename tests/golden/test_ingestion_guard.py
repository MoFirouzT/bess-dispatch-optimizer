"""Golden oracles for the anomaly-aware ingestion guard (R1.4c).

Spec: ``docs/specs/R1.4c-ingestion-guard.md`` § "Golden oracles". Hand-constructed
feeds with a *known* fault → the exact expected classification and reason. The
un-fakeable counterpart, for data, to the MILP golden oracles: the corruption is
objective (a gap is a gap), so "catch it and label it" is checked against inputs
the implementation cannot fudge.

No new math; no committed real data (synthetic feeds only).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from bess.data.fixtures import PRICE_COL, synthetic_day_ahead
from bess.data.ingestion_guard import (
    DEFAULT_MAX_FLAT_HOURS,
    DEFAULT_MAX_FOCAL_FLAT_HOURS,
    FeedStatus,
    IngestionGuardError,
    classify_series,
    guarded_fetch,
    is_focal_price,
)

BAND = (-600.0, 5000.0)

# Explicit slot counts for the `classify_series` oracles below. Deliberately fixed
# literals, *not* derived from the config defaults: these oracles pin the classifier's
# `>= max_repeat` semantics, which must not move when an operational default is retuned.
MAX_REPEAT = 4  # non-focal run allowance
MAX_FOCAL_REPEAT = 24  # focal-price run allowance

# `guarded_fetch` resolves its thresholds from the config defaults instead, so a
# fixture that must trip *it* has to be derived from those, not from the oracles'
# literals above (hourly series ⇒ one slot per wall-clock hour).
DEFAULT_REPEAT = math.ceil(DEFAULT_MAX_FLAT_HOURS)


def _clean_day(seed: int = 1) -> pd.Series:
    """One synthetic, varying, in-band hourly day → healthy by construction."""
    return synthetic_day_ahead(days=1, seed=seed)


def _stuck_day(seed: int = 1) -> pd.Series:
    """A clean day frozen at an *arbitrary* (non-focal) value, long enough to trip
    `guarded_fetch`'s default non-focal threshold.

    The frozen value is deliberately non-focal: freezing at 0.00 would be judged
    against the much looser focal allowance, because a zero run is plausible market
    behaviour rather than a stuck feed.
    """
    s = _clean_day(seed=seed).copy()
    s.iloc[0 : DEFAULT_REPEAT + 1] = 73.07  # an arbitrary cent, not a focal price
    return s


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
        series,
        sanity_band=BAND,
        max_repeat=MAX_REPEAT,
        max_focal_repeat=MAX_FOCAL_REPEAT,
        expected_slots_per_day=None,
    )


# ── content classification (classify_series) ──────────────────────────────────


def test_oracle1_clean_day_is_healthy():
    status, reason = _classify(_clean_day())
    assert status is FeedStatus.HEALTHY
    assert reason is None


def test_oracle2_stuck_arbitrary_value_is_anomaly_stuck_feed():
    """A run at an arbitrary cent is a frozen feed. The market does not clear at
    exactly €73.07 four hours running; prices move continuously and are quoted to
    the cent, so an arbitrary value repeating has negligible probability."""
    s = _clean_day().copy()
    s.iloc[5 : 5 + MAX_REPEAT] = 73.07
    status, reason = _classify(s)
    assert status is FeedStatus.ANOMALY
    assert reason == "stuck_feed"


def test_oracle2b_same_length_run_at_zero_is_healthy():
    """The shape check's whole point, and the pair to the oracle above: an
    identical-length run at the **€0.00 focal price** is legitimate market behaviour
    (excess supply collapsing the clearing price onto the natural zero bid), so it
    must NOT fire where the arbitrary-value run does.

    Grounded in real data: NL *and* BE both cleared at €0.00 for 8 consecutive hours
    on 2024-03-24. A length-only rule cannot separate these two cases; only the value
    can.
    """
    s = _clean_day().copy()
    s.iloc[5 : 5 + MAX_REPEAT] = 0.0
    status, reason = _classify(s)
    assert status is FeedStatus.HEALTHY
    assert reason is None


def test_oracle2c_overlong_run_at_zero_is_still_anomaly():
    """Focal does not mean unbounded: a whole day pinned at exactly one focal price
    is an all-zeros feed, not a market. Real NL/BE 2024 never exceeded 8 h."""
    n = MAX_FOCAL_REPEAT + 1
    idx = pd.date_range("2024-06-01", periods=n, freq="1h", tz="UTC")
    s = pd.Series(np.zeros(n), index=idx, name=PRICE_COL)
    status, reason = _classify(s)
    assert status is FeedStatus.ANOMALY
    assert reason == "stuck_feed"


def test_oracle2d_band_edge_pin_is_focal_not_stuck():
    """A scarcity pin at the technical cap is structural, not a freeze: the price
    cannot cross the bound, so it flattens there. Principled rather than observed
    (NL/BE 2024 never approached the cap), and it stops a future scarcity event from
    reproducing the zero-run false positive one bound higher."""
    s = _clean_day().copy()
    s.iloc[5 : 5 + MAX_REPEAT] = BAND[1]  # pinned at the SDAC cap
    status, reason = _classify(s)
    assert status is FeedStatus.HEALTHY
    assert reason is None


def test_oracle3_interior_gap_is_anomaly_schema():
    s = _clean_day()
    s = s.drop(s.index[10])  # a missing interior slot → irregular grid
    status, reason = _classify(s)
    assert status is FeedStatus.ANOMALY
    assert reason == "schema:gap"  # genuinely missing data, named as such


def test_oracle3b_resolution_change_is_not_called_a_gap():
    """A resolution change is a regime change, not missing data.

    The 2025-10 SDAC switch (PT60M → PT15M) makes a straddling window irregular, but
    nothing is absent: the feed is complete and correct, it just is not the
    single-frequency series the internal schema carries. Reporting `schema:gap` sends
    an operator hunting for timestamps that were never missing — the conflation
    ADR-0012 exists to prevent, one level down.

    Still ANOMALY: the engine cannot consume a mixed-resolution series, so falling
    back is right. Only the *label* was wrong.
    """
    # The real switch transitions cleanly: the last hourly slot is followed one hour
    # later by the first quarter-hourly one, so the steps are exactly two regimes.
    hourly = pd.date_range("2025-09-30 12:00", periods=8, freq="1h", tz="UTC")  # ..19:00
    quarterly = pd.date_range("2025-09-30 20:00", periods=12, freq="15min", tz="UTC")
    idx = hourly.append(quarterly)
    s = pd.Series(np.linspace(10.0, 60.0, len(idx)), index=idx, name=PRICE_COL)

    status, reason = _classify(s)
    assert status is FeedStatus.ANOMALY
    assert reason == "schema:resolution_change"
    assert reason != "schema:gap"


def test_oracle3c_clustered_gaps_stay_a_gap_not_a_resolution_change():
    """The discriminator is conservative: only cleanly *two long regimes* count as a
    resolution change, so a run of adjacent missing slots is still named a gap."""
    s = _clean_day()
    s = s.drop(s.index[[10, 11]])  # two adjacent missing slots, one odd step
    status, reason = _classify(s)
    assert status is FeedStatus.ANOMALY
    assert reason == "schema:gap"


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
    bad = _stuck_day(seed=4)
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
    with pytest.raises(IngestionGuardError):
        guarded_fetch(lambda: _stuck_day(), last_known_good=None)


def test_fetch_schema_failure_keeps_the_validators_diagnosis(caplog):
    """A schema failure inside the fetch must carry *which rule* failed into the log.

    The loader raises messages like "gaps / irregular freq — steps seen: [15min, 1h]";
    the guard used to keep only `type(exc).__name__` and report `schema:valueerror`, so
    a timezone error, a duplicate timestamp, a resolution change and a truncated window
    were all the same string. That is the conflation ADR-0012 exists to prevent, and it
    left the operator with a Python builtin's name as the entire diagnosis.
    """
    lkg = _clean_day(seed=8)
    msg = "gaps / irregular freq — steps seen: [15min, 1h] (expected a single frequency)"

    def bad_fetch() -> pd.Series:
        raise ValueError(msg)

    with caplog.at_level("WARNING"):
        res = guarded_fetch(bad_fetch, last_known_good=lkg)

    assert res.status is FeedStatus.ANOMALY
    assert res.reason == "schema:invalid"  # stable, greppable token
    assert "valueerror" not in caplog.text.lower()  # not the Python type name
    assert msg in caplog.text  # the actual diagnosis survived


def test_hard_stop_error_names_the_underlying_cause():
    """With no fallback available the raise is the operator's only signal, so the
    validator's message has to reach it too."""

    def bad_fetch() -> pd.Series:
        raise ValueError("gaps / irregular freq — steps seen: [15min, 1h]")

    with pytest.raises(IngestionGuardError, match="steps seen"):
        guarded_fetch(bad_fetch, last_known_good=None)


def test_outage_and_anomaly_are_distinct_in_logs(caplog):
    lkg = _clean_day(seed=6)
    stuck = _stuck_day(seed=7)
    with caplog.at_level("WARNING"):
        guarded_fetch(lambda: (_ for _ in ()).throw(TimeoutError()), last_known_good=lkg)
        guarded_fetch(lambda: stuck, last_known_good=lkg)
    text = caplog.text
    assert "outage" in text and "anomaly" in text  # the two classes are grep-distinct


def test_defaults_clear_the_real_world_flat_runs():
    """The defaults must clear the longest *legitimate* runs real prices contain.

    Measured across NL + BE full-year 2024: 8 h at €0.00 (2024-03-24, a sunny Sunday
    solar glut, both zones in lockstep), and never more than 2 h at any arbitrary
    value. A length-only rule had to clear the 8 h zero run, which forced the
    threshold so loose it could not catch a short freeze; keying on the value lets
    the non-focal bound be *tighter* than the zero run it used to have to admit.

    Pins both bounds **token-free**. The live counterpart re-measures them against
    the real feed (`tests/integration/test_ingestion_guard_live.py`) but is
    token-gated and never runs in CI, so without this they could regress unseen on a
    machine that never fetches.
    """
    real_focal_run_hours = 8  # NL + BE, 2024-03-24 @ €0.00
    real_nonfocal_run_hours = 2  # NL + BE 2024 maximum at any arbitrary value

    assert real_focal_run_hours < math.ceil(DEFAULT_MAX_FOCAL_FLAT_HOURS), (
        f"focal allowance {DEFAULT_MAX_FOCAL_FLAT_HOURS} h does not clear the "
        f"{real_focal_run_hours} h zero run real NL/BE prices contain"
    )
    assert real_nonfocal_run_hours < DEFAULT_REPEAT, (
        f"non-focal allowance {DEFAULT_MAX_FLAT_HOURS} h does not clear the "
        f"{real_nonfocal_run_hours} h arbitrary-value run real NL/BE prices contain"
    )
    # The tightening the shape check buys: an arbitrary-value freeze is now caught
    # well inside the zero run a length-only rule was forced to tolerate.
    assert real_focal_run_hours > DEFAULT_MAX_FLAT_HOURS


def test_focal_prices_are_zero_and_the_band_edges():
    """`is_focal_price` admits exactly the structural points, not a price *level*."""
    assert is_focal_price(0.0, BAND)
    assert is_focal_price(-0.01, BAND)  # a real 3 h run sat here (NL/BE 2024-04-01)
    assert is_focal_price(BAND[0], BAND) and is_focal_price(BAND[1], BAND)
    # Ordinary prices are not focal — including legitimate negatives, which are a
    # different regime (must-run units paying to stay on) and vary continuously.
    for v in (73.07, 62.04, -27.30, -50.0, 0.10):
        assert not is_focal_price(v, BAND), v
