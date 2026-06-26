#!/usr/bin/env python3
"""Worked example — run the backtest on a synthetic day-ahead series and emit figures.

Reproduces the two figures committed under ``docs/figures/`` and prints the headline
metrics. The price series is **synthetic** (``bess.data.fixtures.synthetic_day_ahead``)
so nothing here depends on committed market data. Run:

    uv sync --group examples
    uv run python examples/worked_example.py

Outputs ``docs/figures/example-dispatch-day.svg`` and ``example-baselines.svg``.
"""

from __future__ import annotations

from pathlib import Path

from bess.assets.battery import BatterySpec
from bess.backtest.baselines import solve_window
from bess.backtest.engine import run_backtest
from bess.data.fixtures import synthetic_day_ahead
from bess.viz.backtest_plots import plot_baselines, plot_dispatch_day

FIGURES = Path(__file__).resolve().parent.parent / "docs" / "figures"


def main() -> None:
    prices = synthetic_day_ahead(days=90)
    spec = BatterySpec()  # 1 MWh / 1 MW, η = 0.95
    dt = 1.0

    report = run_backtest(prices, spec, dt=dt, window="1D")

    print("Worked example — 90-day synthetic NL-like day-ahead series, 1 MWh / 1 MW asset")
    print(f"  greedy floor          €{report.greedy.revenue_eur:>10,.2f}")
    print(f"  rolling deployable    €{report.rolling.revenue_eur:>10,.2f}")
    print(f"  perfect-foresight     €{report.perfect_foresight.revenue_eur:>10,.2f}")
    print(f"  rolling / ceiling     {report.pct_of_perfect_foresight:>10.1%}")
    print(f"  uplift vs greedy      €{report.uplift_vs_greedy_eur:>10,.2f}")
    print(f"  annualized ceiling    €{report.annualized_ceiling_per_mwh:>10,.0f} / MWh-yr")
    print(f"  constraints satisfied {report.constraint_satisfaction!s:>10}")

    # Representative day for the dispatch figure: the one with the widest spread,
    # where the charge-low / discharge-high pattern is clearest.
    by_day = list(prices.groupby(prices.index.normalize()))
    day_label, day_series = max(by_day, key=lambda kv: kv[1].max() - kv[1].min())
    day_prices = day_series.astype(float).tolist()
    day_sched, _ = solve_window(day_prices, spec, dt)

    FIGURES.mkdir(parents=True, exist_ok=True)
    fig_day = plot_dispatch_day(
        day_prices, day_sched, spec, dt,
        title=f"Optimal dispatch — {day_label.date()} (widest-spread day)",
    )  # fmt: skip
    fig_day.savefig(FIGURES / "example-dispatch-day.svg", bbox_inches="tight")

    fig_base = plot_baselines(report, title="Backtest baselines — 90-day synthetic series")
    fig_base.savefig(FIGURES / "example-baselines.svg", bbox_inches="tight")

    print(f"\nFigures written to {FIGURES}/")


if __name__ == "__main__":
    main()
