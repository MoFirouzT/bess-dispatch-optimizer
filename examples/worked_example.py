#!/usr/bin/env python3
"""Worked example — run the backtest, print the headline metrics, emit the dispatch figure.

The baselines (greedy / rolling / ceiling) are reported as printed numbers, not a
plot. Reproduces the dispatch figure committed under ``docs/figures/``. The
**committed** figure is built from real ENTSO-E NL day-ahead prices; to reproduce it, set an
ENTSO-E token (``ENTSOE_API_TOKEN``, see ``.env.example``) and run:

    uv sync --group examples
    ENTSOE_API_TOKEN=... uv run python examples/worked_example.py

Without a token it falls back to a **synthetic** NL-like series
(``bess.data.fixtures.synthetic_day_ahead``) so the example always runs, but the
figure then differs from the committed real-data one. No real price data is
committed either way (only the rendered chart).

Outputs ``docs/figures/example-dispatch-day.svg``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from bess.assets.battery import BatterySpec, DegradationSpec, schedule_degradation_cost
from bess.backtest.baselines import solve_window
from bess.backtest.engine import run_backtest
from bess.data.entsoe import fetch_day_ahead
from bess.data.fixtures import synthetic_day_ahead
from bess.viz.backtest_plots import plot_dispatch_day

FIGURES = Path(__file__).resolve().parent.parent / "docs" / "figures"

# Linear wear cost (R1.2) so the example prices degradation, not just arbitrage.
# Grounded at €15 / MWh of storage-side throughput: ≈ €150 / kWh capex over ~5,000
# equivalent full cycles at 2 MWh throughput per cycle. A fixed marginal wear cost
# suppresses the shallow round trips whose spread the pure-arbitrage model would take
# but that do not clear the wear cost.
DEGRADATION = DegradationSpec(cost_per_mwh=15.0)  # c_deg (€/MWh throughput); R1.2 linear

# Real-data window for the committed figures: a full 2024-Q2 (91 days), safely
# hourly (before the 2025-10 SDAC 15-min switch) so dt = 1.0 holds.
REAL_START = pd.Timestamp("2024-04-01", tz="UTC")
REAL_END = pd.Timestamp("2024-06-30 23:00", tz="UTC")


def _load_prices() -> tuple[pd.Series, str, str]:
    """Real NL day-ahead when a token is set, else a synthetic fallback.

    Returns ``(prices, source_label, figure_tag)`` — the label prints to stdout,
    the tag goes into the figure titles.
    """
    if os.environ.get("ENTSOE_API_TOKEN"):
        prices = fetch_day_ahead("NL", REAL_START, REAL_END)
        return prices, "real NL day-ahead (2024-Q2, 91 days)", "real NL, 2024-Q2"
    prices = synthetic_day_ahead(days=90)
    return prices, "synthetic 90-day NL-like series (no token)", "synthetic"


def main() -> None:
    prices, source, tag = _load_prices()
    spec = BatterySpec(degradation=DEGRADATION)  # 1 MWh / 1 MW, η = 0.95
    dt = 1.0

    report = run_backtest(prices, spec, dt=dt, window="1D")

    # Wear priced into the ceiling schedule (all revenues below are net of it).
    ceil = report.perfect_foresight.schedule
    deg_ceiling = schedule_degradation_cost(spec, ceil.p_charge, ceil.p_discharge, dt)
    pf = report.perfect_foresight.revenue_eur
    gross_pf = pf + deg_ceiling

    print(f"Worked example — {source}, 1 MWh / 1 MW asset, wear priced (R1.2)")
    print(f"  greedy floor          €{report.greedy.revenue_eur:>10,.2f}   (net of wear)")
    print(f"  rolling deployable    €{report.rolling.revenue_eur:>10,.2f}   (net of wear)")
    print(f"  perfect-foresight     €{pf:>10,.2f}   (net of wear)")
    print(f"  degradation priced    €{deg_ceiling:>10,.2f}   (ceiling; gross €{gross_pf:,.2f})")
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
        title=f"Optimal dispatch — {day_label.date()} ({tag}, widest-spread day)",
    )  # fmt: skip
    fig_day.savefig(FIGURES / "example-dispatch-day.svg", bbox_inches="tight")

    print(f"\nFigure written to {FIGURES}/example-dispatch-day.svg")


if __name__ == "__main__":
    main()
