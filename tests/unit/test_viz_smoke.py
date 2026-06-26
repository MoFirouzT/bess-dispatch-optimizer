"""Smoke test for the worked-example figures (bess.viz).

matplotlib is an optional dependency (the ``examples`` group), so this skips when
it is absent — which is the case in CI. When present it checks both figures build
on a tiny synthetic series without error; it does not assert pixels.
"""

import pytest

pytest.importorskip("matplotlib")

from bess.assets.battery import BatterySpec  # noqa: E402
from bess.backtest.baselines import solve_window  # noqa: E402
from bess.backtest.engine import run_backtest  # noqa: E402
from bess.data.fixtures import synthetic_day_ahead  # noqa: E402
from bess.viz.backtest_plots import plot_baselines, plot_dispatch_day  # noqa: E402


def test_figures_build_without_error():
    prices = synthetic_day_ahead(days=3)
    spec = BatterySpec()
    report = run_backtest(prices, spec, dt=1.0, window="1D")

    fig_base = plot_baselines(report)
    assert fig_base.axes

    day = prices.iloc[:24].astype(float).tolist()
    sched, _ = solve_window(day, spec, 1.0)
    fig_day = plot_dispatch_day(day, sched, spec, 1.0)
    assert fig_day.axes
