"""Unit tests for the fixture price loader (no network, no real data).

Contract: docs/specs/R1.4a-backtest.md § "Data". Validates the internal schema
(tz-aware UTC, hourly, gap-free, price_eur_mwh) the backtest consumes.
"""

import pandas as pd
import pytest

from bess.data.fixtures import load_prices


def _write(tmp_path, index, values=None):
    n = len(index)
    df = pd.DataFrame({"price_eur_mwh": (values if values is not None else range(n))}, index=index)
    df.index.name = "timestamp"
    path = tmp_path / "da_test.parquet"
    df.to_parquet(path)
    return path


def test_load_prices_roundtrip(tmp_path):
    idx = pd.date_range("2024-01-01", periods=48, freq="1h", tz="UTC")
    path = _write(tmp_path, idx, values=[float(i) for i in range(48)])

    s = load_prices(path)
    assert isinstance(s, pd.Series)
    assert s.name == "price_eur_mwh"
    assert str(s.index.tz) == "UTC"
    assert len(s) == 48
    assert s.iloc[0] == 0.0 and s.iloc[-1] == 47.0


def test_load_prices_rejects_naive_index(tmp_path):
    idx = pd.date_range("2024-01-01", periods=24, freq="1h")  # tz-naive
    path = _write(tmp_path, idx)
    with pytest.raises(ValueError, match="UTC"):
        load_prices(path)


def test_load_prices_rejects_gaps(tmp_path):
    idx = pd.date_range("2024-01-01", periods=24, freq="1h", tz="UTC").delete(5)  # missing hour
    path = _write(tmp_path, idx)
    with pytest.raises(ValueError, match="gap|regular|freq"):
        load_prices(path)
