"""Property gates for the ingestion guard (R1.5b).

Spec: ``docs/specs/R1.5b-ingestion-guard.md`` § "Property tests". The same
"inputs the implementation did not choose" discipline the MILP invariants apply
to constraints, applied to data:

- no corrupted series ever passes as HEALTHY (injected zeros-block, gap,
  duplicate, out-of-band, NaN);
- no false positive: a schema-valid, fault-free series with arbitrary in-band
  prices (including legitimate negatives/zeros) is always HEALTHY;
- transport failures classify OUTAGE, content faults classify ANOMALY — the two
  never collide.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from bess.data.fixtures import PRICE_COL
from bess.data.ingestion_guard import FeedStatus, classify_series, guarded_fetch

BAND = (-600.0, 5000.0)
MAX_REPEAT = 8


def _classify(s: pd.Series):
    return classify_series(s, sanity_band=BAND, max_repeat=MAX_REPEAT, expected_slots_per_day=None)


@st.composite
def clean_series(draw, min_len: int = 24, max_len: int = 72) -> pd.Series:
    """A schema-valid, fault-free, *varying*, in-band hourly series.

    Values may be negative or zero (legitimate market conditions), but a strictly
    increasing micro-offset guarantees no run of bit-identical values, so a clean
    series can never accidentally look like a stuck feed.
    """
    n = draw(st.integers(min_value=min_len, max_value=max_len))
    base = draw(
        st.lists(
            st.floats(min_value=-100.0, max_value=300.0, allow_nan=False, allow_infinity=False),
            min_size=n,
            max_size=n,
        )
    )
    vals = np.clip(np.asarray(base, dtype=float), BAND[0] + 1.0, BAND[1] - 1.0)
    vals = vals + np.arange(n) * 1e-6  # distinct consecutive values, negligible shift
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.Series(vals, index=idx, name=PRICE_COL)


@given(clean_series())
@settings(max_examples=75)
def test_clean_varying_series_never_flagged(s: pd.Series):
    # No false positives — legitimate in-band data (incl. negatives/zeros) is healthy.
    status, reason = _classify(s)
    assert status is FeedStatus.HEALTHY, f"false positive: reason={reason}"


@given(clean_series(), st.sampled_from(["stuck", "gap", "dup", "band", "nan"]))
@settings(max_examples=120)
def test_injected_fault_never_passes_as_healthy(s: pd.Series, fault: str):
    mid = len(s) // 2
    if fault == "stuck":
        s = s.copy()
        s.iloc[0:MAX_REPEAT] = 0.0
        expected, prefix = "stuck_feed", False
    elif fault == "gap":
        s = s.drop(s.index[mid])
        expected, prefix = "schema:", True
    elif fault == "dup":
        s = pd.concat([s, s.iloc[[mid]]]).sort_index()
        expected, prefix = "schema:", True
    elif fault == "band":
        s = s.copy()
        s.iloc[mid] = 1e6
        expected, prefix = "out_of_band", False
    else:  # nan
        s = s.copy()
        s.iloc[mid] = np.nan
        expected, prefix = "non_finite", False

    status, reason = _classify(s)
    assert status is FeedStatus.ANOMALY
    if prefix:
        assert reason.startswith(expected)
    else:
        assert reason == expected


@given(st.sampled_from(["timeout", "conn", "other"]))
@settings(max_examples=15)
def test_transport_error_classifies_as_outage(kind: str):
    lkg = pd.Series(
        np.linspace(10.0, 50.0, 24),
        index=pd.date_range("2024-01-01", periods=24, freq="1h", tz="UTC"),
        name=PRICE_COL,
    )

    def boom() -> pd.Series:
        if kind == "timeout":
            raise TimeoutError()
        if kind == "conn":
            raise ConnectionError()
        raise RuntimeError("5xx")

    res = guarded_fetch(boom, last_known_good=lkg)
    assert res.status is FeedStatus.OUTAGE
    assert res.degraded is True
