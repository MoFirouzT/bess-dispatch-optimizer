"""Unit tests for the ENTSO-E day-ahead adapter (no network, no real data, no token).

Contract: docs/specs/R1.4b-entsoe-loader.md § "Interfaces" / "Acceptance gate".
The live fetch is exercised via a fake client (monkeypatch) so the normalization,
schema validation, and parquet cache paths are covered token-free. The genuine
live call lives in the token-gated integration test, never in CI.
"""

import pandas as pd
import pytest

from bess.data.entsoe import fetch_day_ahead


def _fake_client_factory(raw, calls):
    """A drop-in for EntsoePandasClient that returns `raw` and counts queries."""

    class _FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key

        def query_day_ahead_prices(self, zone, start, end):
            calls["n"] += 1
            return raw

    return _FakeClient


def test_fetch_normalizes_local_tz_to_utc_and_caches(tmp_path, monkeypatch):
    # entsoe-py returns the series in the bidding-zone local tz; the adapter must
    # convert to UTC and rename to the internal column.
    idx = pd.date_range("2024-06-01 00:00", periods=48, freq="1h", tz="Europe/Amsterdam")
    raw = pd.Series(range(48), index=idx, dtype=float, name="anything")
    calls = {"n": 0}
    monkeypatch.setattr("bess.data.entsoe.EntsoePandasClient", _fake_client_factory(raw, calls))

    start = pd.Timestamp("2024-06-01", tz="UTC")
    end = pd.Timestamp("2024-06-03", tz="UTC")

    s1 = fetch_day_ahead("NL", start, end, api_token="dummy", cache_dir=tmp_path)
    assert str(s1.index.tz) == "UTC"
    assert s1.name == "price_eur_mwh"
    assert len(s1) == 48
    assert (s1.index.to_series().diff().dropna() == pd.Timedelta(hours=1)).all()
    assert calls["n"] == 1

    # Second call is served from the parquet cache — no second API query.
    s2 = fetch_day_ahead("NL", start, end, api_token="dummy", cache_dir=tmp_path)
    assert calls["n"] == 1
    pd.testing.assert_series_equal(s1, s2, check_freq=False)


def test_fetch_lowercase_zone_accepted(tmp_path, monkeypatch):
    idx = pd.date_range("2024-06-01 00:00", periods=24, freq="1h", tz="Europe/Brussels")
    raw = pd.Series(range(24), index=idx, dtype=float)
    monkeypatch.setattr("bess.data.entsoe.EntsoePandasClient", _fake_client_factory(raw, {"n": 0}))
    s = fetch_day_ahead(
        "be",
        pd.Timestamp("2024-06-01", tz="UTC"),
        pd.Timestamp("2024-06-02", tz="UTC"),
        api_token="dummy",
    )
    assert s.name == "price_eur_mwh"


def test_fetch_rejects_unsupported_zone():
    with pytest.raises(ValueError, match="zone"):
        fetch_day_ahead(
            "FR",
            pd.Timestamp("2024-06-01", tz="UTC"),
            pd.Timestamp("2024-06-02", tz="UTC"),
            api_token="dummy",
        )


def test_fetch_requires_token(monkeypatch):
    monkeypatch.delenv("ENTSOE_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="ENTSOE_API_TOKEN"):
        fetch_day_ahead(
            "NL",
            pd.Timestamp("2024-06-01", tz="UTC"),
            pd.Timestamp("2024-06-02", tz="UTC"),
        )
