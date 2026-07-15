"""Unit tests for the ENTSO-E day-ahead adapter (no network, no real data, no token).

Contract: docs/specs/R1.4b-entsoe-loader.md § "Interfaces" / "Acceptance gate".
The live fetch is exercised via a fake client (monkeypatch) so the normalization,
schema validation, and parquet cache paths are covered token-free. The genuine
live call lives in the token-gated integration test, never in CI.
"""

import pandas as pd
import pytest

from bess.data.entsoe import _cache_path, fetch_day_ahead
from bess.data.fixtures import PRICE_COL


def _fake_client_factory(raw, calls):
    """A drop-in for EntsoePandasClient that returns `raw` and counts queries."""

    class _FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key

        def query_day_ahead_prices(self, zone, start, end):
            calls["n"] += 1
            return raw

    return _FakeClient


def _local_raw(first, last, tz, freq="1h"):
    """A raw entsoe-py-shaped series: prices in the bidding-zone local tz, spanning
    `[first, last]` **inclusive** — ENTSO-E's `end` is inclusive, verified against
    the live API (a 3-day hourly fetch returns 73 points, not 72).
    """
    idx = pd.date_range(first, last, freq=freq, tz="UTC").tz_convert(tz)
    return pd.Series(range(len(idx)), index=idx, dtype=float, name="anything")


def test_fetch_normalizes_local_tz_to_utc_and_caches(tmp_path, monkeypatch):
    # entsoe-py returns the series in the bidding-zone local tz; the adapter must
    # convert to UTC and rename to the internal column.
    start = pd.Timestamp("2024-06-01", tz="UTC")
    end = pd.Timestamp("2024-06-03", tz="UTC")
    raw = _local_raw(start, end, "Europe/Amsterdam")
    calls = {"n": 0}
    monkeypatch.setattr("bess.data.entsoe.EntsoePandasClient", _fake_client_factory(raw, calls))

    s1 = fetch_day_ahead("NL", start, end, api_token="dummy", cache_dir=tmp_path)
    assert str(s1.index.tz) == "UTC"
    assert s1.name == "price_eur_mwh"
    assert len(s1) == 49  # 48 hourly steps, both endpoints inclusive
    assert (s1.index.to_series().diff().dropna() == pd.Timedelta(hours=1)).all()
    assert calls["n"] == 1

    # Second call is served from the parquet cache — no second API query.
    s2 = fetch_day_ahead("NL", start, end, api_token="dummy", cache_dir=tmp_path)
    assert calls["n"] == 1
    pd.testing.assert_series_equal(s1, s2, check_freq=False)


def test_fetch_lowercase_zone_accepted(tmp_path, monkeypatch):
    start = pd.Timestamp("2024-06-01", tz="UTC")
    end = pd.Timestamp("2024-06-02", tz="UTC")
    raw = _local_raw(start, end, "Europe/Brussels")
    monkeypatch.setattr("bess.data.entsoe.EntsoePandasClient", _fake_client_factory(raw, {"n": 0}))
    s = fetch_day_ahead("be", start, end, api_token="dummy")
    assert s.name == "price_eur_mwh"


def test_fetch_rejects_unsupported_zone():
    with pytest.raises(ValueError, match="zone"):
        fetch_day_ahead(
            "FR",
            pd.Timestamp("2024-06-01", tz="UTC"),
            pd.Timestamp("2024-06-02", tz="UTC"),
            api_token="dummy",
        )


def test_fetch_rejects_tail_truncated_window(monkeypatch):
    """ENTSO-E published nothing for the last day of the window.

    The returned series is still perfectly regular, so `validate_price_series` passes
    it; only the requested window reveals the missing day. Guards the docstring's
    promise of a series "over [start, end]".
    """
    start = pd.Timestamp("2024-06-01", tz="UTC")
    end = pd.Timestamp("2024-06-03", tz="UTC")
    raw = _local_raw(start, pd.Timestamp("2024-06-02", tz="UTC"), "Europe/Amsterdam")
    monkeypatch.setattr("bess.data.entsoe.EntsoePandasClient", _fake_client_factory(raw, {"n": 0}))
    with pytest.raises(ValueError, match="does not cover"):
        fetch_day_ahead("NL", start, end, api_token="dummy")


def test_fetch_rejects_head_truncated_window(monkeypatch):
    """Same blind spot at the other end: the window's first day is missing."""
    start = pd.Timestamp("2024-06-01", tz="UTC")
    end = pd.Timestamp("2024-06-03", tz="UTC")
    raw = _local_raw(pd.Timestamp("2024-06-02", tz="UTC"), end, "Europe/Amsterdam")
    monkeypatch.setattr("bess.data.entsoe.EntsoePandasClient", _fake_client_factory(raw, {"n": 0}))
    with pytest.raises(ValueError, match="does not cover"):
        fetch_day_ahead("NL", start, end, api_token="dummy")


def test_fetch_rejects_empty_window(monkeypatch):
    """An empty series is vacuously regular — `validate_price_series` skips its step
    check below two points — so it too needs the window to be caught."""
    raw = pd.Series([], index=pd.DatetimeIndex([], tz="UTC"), dtype=float)
    monkeypatch.setattr("bess.data.entsoe.EntsoePandasClient", _fake_client_factory(raw, {"n": 0}))
    with pytest.raises(ValueError, match="no price points"):
        fetch_day_ahead(
            "NL",
            pd.Timestamp("2024-06-01", tz="UTC"),
            pd.Timestamp("2024-06-03", tz="UTC"),
            api_token="dummy",
        )


def test_fetch_rejects_truncated_cache(tmp_path):
    """A truncated series already on disk must not bypass the window check: the cache
    path returns before the API call, so it needs the check independently."""
    start = pd.Timestamp("2024-06-01", tz="UTC")
    end = pd.Timestamp("2024-06-03", tz="UTC")
    cached = _local_raw(start, pd.Timestamp("2024-06-02", tz="UTC"), "UTC")
    cached.name = PRICE_COL
    path = _cache_path(tmp_path, "NL", start, end)
    path.parent.mkdir(parents=True, exist_ok=True)
    cached.to_frame().to_parquet(path)

    with pytest.raises(ValueError, match="does not cover"):
        fetch_day_ahead("NL", start, end, api_token="dummy", cache_dir=tmp_path)


def test_fetch_requires_token(monkeypatch):
    monkeypatch.delenv("ENTSOE_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="ENTSOE_API_TOKEN"):
        fetch_day_ahead(
            "NL",
            pd.Timestamp("2024-06-01", tz="UTC"),
            pd.Timestamp("2024-06-02", tz="UTC"),
        )
