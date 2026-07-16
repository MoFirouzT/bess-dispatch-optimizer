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
from bess.viz.backtest_plots import plot_dispatch_day  # noqa: E402
from bess.viz.explain_plots import plot_water_value  # noqa: E402
from bess.viz.stochastic_plots import (  # noqa: E402
    plot_risk_return_frontier,
    plot_vss_curve,
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
