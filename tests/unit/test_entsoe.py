"""Unit tests for the ENTSO-E day-ahead adapter (no network, no real data, no token).

Contract: docs/specs/data-feed.md § "Interfaces" / "Acceptance gate".
The live fetch is exercised via a fake client (monkeypatch) so the normalization,
schema validation, and parquet cache paths are covered token-free. The genuine
live call lives in the token-gated integration test, never in CI.
"""

import pandas as pd
import pytest

from bess.data.entsoe import CACHE_DIR_ENV, _cache_path, fetch_day_ahead
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


# --- cache-directory resolution (explicit arg > $BESS_CACHE_DIR > no cache) ------
#
# The cache is opt-in, and for most of this project's life nothing opted in: every
# integration test and example called `fetch_day_ahead` bare, so each run re-pulled
# the same frozen history. The env var opts a whole session in without threading a
# path through every call site. These tests pin the three-way precedence, because
# each branch is load-bearing: the explicit argument keeps a caller's private cache
# private, and "unset means no cache" is what keeps CI's behaviour unchanged.


def test_cache_dir_defaults_to_env_var(tmp_path, monkeypatch):
    """With no `cache_dir=`, `$BESS_CACHE_DIR` supplies one — the whole point."""
    start = pd.Timestamp("2024-06-01", tz="UTC")
    end = pd.Timestamp("2024-06-03", tz="UTC")
    raw = _local_raw(start, end, "Europe/Amsterdam")
    calls = {"n": 0}
    monkeypatch.setattr("bess.data.entsoe.EntsoePandasClient", _fake_client_factory(raw, calls))
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path))

    s1 = fetch_day_ahead("NL", start, end, api_token="dummy")
    assert calls["n"] == 1
    assert _cache_path(tmp_path, "NL", start, end).exists()

    s2 = fetch_day_ahead("NL", start, end, api_token="dummy")
    assert calls["n"] == 1  # served from the env-supplied cache
    pd.testing.assert_series_equal(s1, s2, check_freq=False)


def test_explicit_cache_dir_wins_over_env_var(tmp_path, monkeypatch):
    """A caller asking for a specific cache must not be redirected by the environment.

    Unit tests hand in `tmp_path` precisely so their cache is isolated; if the env
    var could override that, a developer with `BESS_CACHE_DIR` exported would have
    those tests reading and writing the shared on-disk cache.
    """
    env_dir, explicit_dir = tmp_path / "env", tmp_path / "explicit"
    start = pd.Timestamp("2024-06-01", tz="UTC")
    end = pd.Timestamp("2024-06-03", tz="UTC")
    raw = _local_raw(start, end, "Europe/Amsterdam")
    monkeypatch.setattr("bess.data.entsoe.EntsoePandasClient", _fake_client_factory(raw, {"n": 0}))
    monkeypatch.setenv(CACHE_DIR_ENV, str(env_dir))

    fetch_day_ahead("NL", start, end, api_token="dummy", cache_dir=explicit_dir)
    assert _cache_path(explicit_dir, "NL", start, end).exists()
    assert not env_dir.exists()


@pytest.mark.parametrize("env_value", [None, "", "   "])
def test_no_cache_without_an_env_var(env_value, monkeypatch, tmp_path):
    """Unset (or blank) means no cache at all: two fetches, two API calls, no files.

    Blank counts as unset because `export BESS_CACHE_DIR=` is how a shell clears it
    in practice, and `Path("")` would otherwise resolve to the current working
    directory and scatter parquet files across the repo.
    """
    start = pd.Timestamp("2024-06-01", tz="UTC")
    end = pd.Timestamp("2024-06-03", tz="UTC")
    raw = _local_raw(start, end, "Europe/Amsterdam")
    calls = {"n": 0}
    monkeypatch.setattr("bess.data.entsoe.EntsoePandasClient", _fake_client_factory(raw, calls))
    if env_value is None:
        monkeypatch.delenv(CACHE_DIR_ENV, raising=False)
    else:
        monkeypatch.setenv(CACHE_DIR_ENV, env_value)
    monkeypatch.chdir(tmp_path)

    fetch_day_ahead("NL", start, end, api_token="dummy")
    fetch_day_ahead("NL", start, end, api_token="dummy")
    assert calls["n"] == 2
    assert list(tmp_path.iterdir()) == []


def test_fetch_requires_token(monkeypatch):
    monkeypatch.delenv("ENTSOE_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="ENTSOE_API_TOKEN"):
        fetch_day_ahead(
            "NL",
            pd.Timestamp("2024-06-01", tz="UTC"),
            pd.Timestamp("2024-06-02", tz="UTC"),
        )
