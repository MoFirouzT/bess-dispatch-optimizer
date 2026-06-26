"""The pandas-Series + '1D' windowing path (token-free, synthetic series).

The golden/property tests drive the integer-window (sequence) path; this exercises
the calendar-day grouping the real fixture will use.
"""

import numpy as np
import pandas as pd

from bess.assets.battery import BatterySpec
from bess.backtest.engine import run_backtest


def test_daily_windowing_groups_by_utc_calendar_day():
    # Two UTC days, hourly: day 1 buy-low/sell-high, day 2 flat.
    idx = pd.date_range("2024-01-01", periods=48, freq="1h", tz="UTC")
    rng = np.random.default_rng(0)
    prices = np.concatenate([rng.uniform(10, 90, 24), np.full(24, 50.0)])
    series = pd.Series(prices, index=idx, name="price_eur_mwh")

    spec = BatterySpec(eta_charge=1.0, eta_discharge=1.0)
    rep = run_backtest(series, spec, dt=1.0, window="1D")

    # Rolling/greedy segment per calendar day; ceiling is one global window.
    assert rep.rolling.window_sizes == [24, 24]
    assert rep.greedy.window_sizes == [24, 24]
    assert rep.perfect_foresight.window_sizes == [48]
    # Ordering + well-formed metric hold on the real-shaped path too.
    assert rep.greedy.revenue_eur <= rep.rolling.revenue_eur + 1e-6
    assert rep.rolling.revenue_eur <= rep.perfect_foresight.revenue_eur + 1e-6
    assert 0.0 <= rep.pct_of_perfect_foresight <= 1.0 + 1e-6
    assert rep.constraint_satisfaction
