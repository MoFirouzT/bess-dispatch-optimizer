#!/usr/bin/env python3
"""Duration sweep — run the backtest across storage durations, print the table, emit the figure.

Storage duration is the energy-to-power ratio (a 1 MWh / 1 MW asset is 1-hour;
4 MWh / 1 MW is 4-hour). The optimizer math is scale-invariant in duration, but the
economics are not, so a single-duration headline can misstate the general result
(ADR-0022). This runs the walk-forward backtest at {1h, 2h, 4h} with power fixed and
reports the capture ratio and per-MWh ceiling per duration.

The **committed** figure is built from real ENTSO-E NL day-ahead prices; to reproduce it:

    uv sync --group examples
    ENTSOE_API_TOKEN=... uv run python examples/duration_sweep.py

Without a token it falls back to a **synthetic** NL-like series so the example always
runs (the figure then differs from the committed real-data one). No real price data is
committed either way (only the rendered chart).

Outputs ``docs/figures/example-duration-sweep.svg``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from bess.assets.battery import BatterySpec, DegradationSpec
from bess.backtest.engine import run_duration_sweep
from bess.data.entsoe import fetch_day_ahead
from bess.data.fixtures import synthetic_day_ahead
from bess.viz.backtest_plots import plot_duration_sweep

FIGURES = Path(__file__).resolve().parent.parent / "docs" / "figures"

# Linear wear cost (R1.2) so the sweep prices degradation, not just arbitrage.
DEGRADATION = DegradationSpec(cost_per_mwh=15.0)  # c_deg (€/MWh throughput); R1.2 linear

DURATIONS = (1.0, 2.0, 4.0)  # storage durations (h); power held fixed at 1 MW

# Real-data window for the committed figure: a full 2024-Q2 (91 days), safely hourly.
REAL_START = pd.Timestamp("2024-04-01", tz="UTC")
REAL_END = pd.Timestamp("2024-06-30 23:00", tz="UTC")


def _load_prices() -> tuple[pd.Series, str, str]:
    """Real NL day-ahead when a token is set, else a synthetic fallback."""
    if os.environ.get("ENTSOE_API_TOKEN"):
        prices = fetch_day_ahead("NL", REAL_START, REAL_END)
        return prices, "real NL day-ahead (2024-Q2, 91 days)", "real NL, 2024-Q2"
    prices = synthetic_day_ahead(days=90)
    return prices, "synthetic 90-day NL-like series (no token)", "synthetic"


def main() -> None:
    prices, source, tag = _load_prices()
    base = BatterySpec(degradation=DEGRADATION)  # 1 MW power; capacity varies by duration
    results = run_duration_sweep(prices, base, dt=1.0, durations=DURATIONS)

    print(f"Duration sweep on {source} (power fixed at {base.p_discharge_max:g} MW):\n")
    print(f"  {'duration':>9}  {'capacity':>9}  {'captured':>9}  {'ceiling €/MWh-yr':>17}")
    for r in results:
        print(
            f"  {r.duration_h:>8g}h  {r.capacity_mwh:>7g} MWh  "
            f"{100.0 * r.pct_of_perfect_foresight:>8.1f}%  {r.annualized_ceiling_per_mwh:>17,.0f}"
        )
    print(
        "\nCapture ratio falls and per-MWh value diminishes as duration rises "
        "(cross-day carry grows; each added hour arbitrages a flatter spread)."
    )

    fig = plot_duration_sweep(
        [r.duration_h for r in results],
        [r.pct_of_perfect_foresight for r in results],
        [r.annualized_ceiling_per_mwh for r in results],
        title=f"Storage duration sweep — {tag}",
    )
    FIGURES.mkdir(parents=True, exist_ok=True)
    out = FIGURES / "example-duration-sweep.svg"
    fig.savefig(out, format="svg", bbox_inches="tight")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
