"""Suite-wide fixtures.

Currently one job: keep the test suite hermetic against the developer's shell.
"""

import pytest

from bess.data.entsoe import CACHE_DIR_ENV


@pytest.fixture(autouse=True)
def _no_inherited_price_cache(monkeypatch):
    """Unset `$BESS_CACHE_DIR` for every test, so no test inherits a real cache.

    The loader falls back to that variable when no `cache_dir=` is passed, which is
    what lets the live integration tests and the examples share one on-disk cache.
    Without this fixture a developer who exported it would silently change what the
    unit and property tests exercise: the tests that assert an endpoint was called
    exactly once would start reading real parquet from `data/cache/` instead of the
    fake client, and would pass for the wrong reason (or fail on a foreign window).

    Tests that want a cache set the variable themselves (or pass `cache_dir=`), and
    `tests/integration/conftest.py` re-enables it for the live tests. Overriding an
    autouse fixture's effect this way is fine: `monkeypatch` restores the original
    environment after each test either way.
    """
    monkeypatch.delenv(CACHE_DIR_ENV, raising=False)
