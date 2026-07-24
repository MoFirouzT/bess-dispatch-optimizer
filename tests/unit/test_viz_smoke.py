"""Smoke test for the plotting functions (bess.viz).

matplotlib is an optional dependency (the ``examples`` group), so this skips when
it is absent — which is the case in CI. When present it checks the figures build
on a tiny synthetic series without error; it does not assert pixels.

The `examples/` scripts that *call* these live in ``test_examples_smoke.py``.
"""

import pytest

pytest.importorskip("matplotlib")

from bess.assets.battery import BatterySpec  # noqa: E402
from bess.backtest.baselines import solve_window  # noqa: E402
from bess.data.fixtures import synthetic_day_ahead  # noqa: E402
from bess.viz.backtest_plots import plot_dispatch_day, plot_spike_tail  # noqa: E402
from bess.viz.explain_plots import plot_water_value  # noqa: E402
from bess.viz.forecast_plots import (  # noqa: E402
    plot_drift_regions,
    plot_forecast_intervals,
)
from bess.viz.stochastic_plots import (  # noqa: E402
    plot_risk_return_frontier,
    plot_vss_curve,
    plot_vss_distribution,
)


def test_figures_build_without_error():
    prices = synthetic_day_ahead(days=3)
    spec = BatterySpec()

    day = prices.iloc[:24].astype(float).tolist()
    sched, _ = solve_window(day, spec, 1.0)
    fig_day = plot_dispatch_day(day, sched, spec, 1.0)
    assert fig_day.axes


def test_stochastic_figures_build_without_error():
    lambdas = [0.0, 0.3, 0.6, 0.9]
    fig_frontier = plot_risk_return_frontier(
        expected_profit=[40.0, 39.0, 38.0, 37.5],
        cvar_loss=[-30.0, -33.0, -35.0, -36.0],
        lambdas=lambdas,
    )
    assert fig_frontier.axes

    fig_vss = plot_vss_curve(rhos=[0.0, 0.2, 0.5, 1.0, 2.0], vss=[0.0, 3.0, 6.0, 2.0, 0.0])
    assert fig_vss.axes

    fig_dist = plot_vss_distribution([2.0, -0.5, 4.0, 0.0, 1.5, 3.2, -1.1, 0.8])
    assert fig_dist.axes


def test_forecast_interval_figure_builds_without_error():
    # The plot takes raw sequences (no LightGBM), so it needs no forecast group.
    hours = list(range(6))
    fig = plot_forecast_intervals(
        hours=hours,
        point=[10.0, 12.0, 40.0, 38.0, 15.0, 11.0],
        lower=[5.0, 7.0, 30.0, 28.0, 9.0, 6.0],
        upper=[16.0, 18.0, 52.0, 49.0, 22.0, 17.0],
        realized=[9.0, 13.0, 44.0, 33.0, 60.0, 10.0],  # one point outside the band
        confidence_level=0.9,
        coverage=0.9,
    )
    assert fig.axes


def test_spike_tail_figure_builds_without_error():
    fig = plot_spike_tail(
        residuals=[-5.0, 0.0, 3.0, 8.0, 25.0, 40.0, -2.0, 1.0],
        threshold=20.0,
        gpd_x=[20.0, 30.0, 40.0, 50.0],
        gpd_density=[0.05, 0.02, 0.008, 0.003],
        hist_max_price=300.0,
        tail_max_price=900.0,
    )
    assert fig.axes


def test_drift_regions_figure_builds_without_error():
    # A 2x2 status grid (codes) with a legend and a couple of example windows.
    codes = [[0, 0], [1, 2]]
    legend = [(0, "healthy", "#2a9d8f"), (1, "regime", "#e9c46a"), (2, "staleness", "#e76f51")]
    fig = plot_drift_regions(
        ratios=[0.8, 1.6],
        psis=[0.05, 0.35],
        status_codes=codes,
        legend=legend,
        points=[(0.9, 0.05, "healthy"), (1.5, 0.1, "staleness")],
    )
    assert fig.axes


def test_water_value_figure_builds_without_error():
    # A three-period explanation with a band and an idle period; None edges tolerated.
    fig = plot_water_value(
        prices=[10.0, 100.0, 200.0],
        water_value=[100.0, 100.0, 100.0],
        band_low=[100.0, 100.0, 100.0],
        band_high=[100.0, 100.0, 100.0],
        actions=["charge", "idle", "discharge"],
    )
    assert fig.axes
