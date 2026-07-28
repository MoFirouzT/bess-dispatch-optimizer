"""Fixtures for the token-gated live ENTSO-E tests.

These tests pull real history, and a lot of it: the ingestion-guard test alone
fetches a full year for each of NL and BE. The windows are almost all *historical*
and therefore frozen — day-ahead prices are settled auction results, final once
published — so re-fetching them on every run buys nothing and costs a slow,
rate-limited round trip per test. This directory caches to disk; the loader keys
each parquet on `(kind, zone, start, end)`, so a moving window (the guard's
"last complete month") simply misses and re-fetches when it moves.

The cache lives under `data/cache/`, gitignored: nothing fetched is committed
(docs/decisions/no-committed-market-data.md). It is pure derived data and safe to delete at any
time.
"""

import os
from pathlib import Path

import pytest

from bess.data.entsoe import CACHE_DIR_ENV

# tests/integration/conftest.py → repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = _REPO_ROOT / "data" / "cache"

# Read at import (collection time), which is before any fixture runs. The root
# conftest clears this variable per test for hermeticity, so by the time the fixture
# below executes the developer's own export is no longer visible in os.environ.
_EXPORTED_CACHE_DIR = os.environ.get(CACHE_DIR_ENV, "").strip()


@pytest.fixture(autouse=True)
def _price_cache(monkeypatch, request):
    """Point the live tests at the on-disk price cache.

    Honours an explicitly exported `$BESS_CACHE_DIR` and otherwise defaults to
    `data/cache/`. A module opts out of caching entirely by setting
    `uses_live_api = True` — see `test_entsoe_live.py`, which exists to catch
    ENTSO-E schema drift and would prove nothing served from parquet.
    """
    if getattr(request.module, "uses_live_api", False):
        return
    monkeypatch.setenv(CACHE_DIR_ENV, _EXPORTED_CACHE_DIR or str(DEFAULT_CACHE_DIR))
